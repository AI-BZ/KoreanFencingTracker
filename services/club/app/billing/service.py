"""
Billing Service - 청구/결제 비즈니스 로직
"""

import uuid
from datetime import date, datetime
from typing import Optional, List, Tuple
from loguru import logger

from ..database import get_supabase_client
from .models import (
    InvoiceStatus,
    InvoiceMemberStatus,
    PaymentMethod,
    PaymentStatus,
    SplitType,
    InvoiceType,
    BillingRunResult,
    OverdueAlert,
)
from .portone import portone_client, PortOneError


class BillingService:
    """청구/결제 서비스"""

    def __init__(self):
        pass

    @property
    def supabase(self):
        return get_supabase_client()

    # ─────────────────────────────────────────
    # 청구서 CRUD
    # ─────────────────────────────────────────

    def create_invoice(
        self,
        org_id: int,
        created_by: str,
        title: str,
        invoice_type: str,
        total_amount: int,
        member_ids: List[str],
        split_type: str = "none",
        description: Optional[str] = None,
        due_date: Optional[date] = None,
        competition_id: Optional[int] = None,
        custom_amounts: Optional[List[int]] = None,
    ) -> dict:
        """청구서 생성 + 멤버별 청구 레코드"""

        # 청구서 생성
        invoice_data = {
            "org_id": org_id,
            "created_by": created_by,
            "title": title,
            "description": description,
            "invoice_type": invoice_type,
            "total_amount": total_amount,
            "due_date": due_date.isoformat() if due_date else None,
            "status": InvoiceStatus.draft.value,
            "split_type": split_type,
            "target_count": len(member_ids),
            "competition_id": competition_id,
        }

        result = self.supabase.table("app_invoices").insert(invoice_data).execute()
        invoice = result.data[0]
        invoice_id = invoice["id"]

        # 멤버별 금액 계산
        if split_type == SplitType.equal.value:
            per_member = total_amount // len(member_ids)
            remainder = total_amount % len(member_ids)
            member_amounts = [per_member] * len(member_ids)
            # 나머지는 첫 번째 멤버에게
            if remainder > 0:
                member_amounts[0] += remainder
        elif split_type == SplitType.custom.value and custom_amounts:
            member_amounts = custom_amounts
        else:
            # none: 각 멤버에게 total_amount 전액
            member_amounts = [total_amount] * len(member_ids)

        # 멤버별 청구 레코드 생성
        for member_id, amount in zip(member_ids, member_amounts):
            self.supabase.table("app_invoice_members").insert({
                "invoice_id": invoice_id,
                "member_id": member_id,
                "amount": amount,
                "status": InvoiceMemberStatus.pending.value,
            }).execute()

        return invoice

    def get_invoice(self, invoice_id: int, org_id: int) -> Optional[dict]:
        """청구서 상세 조회 (멤버 포함)"""
        result = self.supabase.table("app_invoices").select(
            "*, members!app_invoices_created_by_fkey(full_name)"
        ).eq("id", invoice_id).eq("org_id", org_id).single().execute()

        if not result.data:
            return None

        invoice = result.data

        # 멤버별 청구 조회
        members_result = self.supabase.table("app_invoice_members").select(
            "*, members!app_invoice_members_member_id_fkey(full_name)"
        ).eq("invoice_id", invoice_id).execute()

        invoice["invoice_members"] = []
        for m in (members_result.data or []):
            member_info = m.get("members", {}) or {}
            invoice["invoice_members"].append({
                **m,
                "member_name": member_info.get("full_name"),
            })

        creator_info = invoice.get("members", {}) or {}
        invoice["creator_name"] = creator_info.get("full_name")

        return invoice

    def list_invoices(
        self,
        org_id: int,
        status: Optional[str] = None,
        invoice_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[dict], int]:
        """청구서 목록"""
        query = self.supabase.table("app_invoices").select(
            "*, members!app_invoices_created_by_fkey(full_name)",
            count="exact"
        ).eq("org_id", org_id)

        if status:
            query = query.eq("status", status)
        if invoice_type:
            query = query.eq("invoice_type", invoice_type)

        result = query.order("created_at", desc=True).range(
            offset, offset + limit - 1
        ).execute()

        invoices = []
        for inv in (result.data or []):
            creator_info = inv.get("members", {}) or {}
            # 멤버 카운트
            members_count = self.supabase.table("app_invoice_members").select(
                "id", count="exact"
            ).eq("invoice_id", inv["id"]).execute()

            paid_count = self.supabase.table("app_invoice_members").select(
                "id", count="exact"
            ).eq("invoice_id", inv["id"]).eq("status", "paid").execute()

            invoices.append({
                **inv,
                "creator_name": creator_info.get("full_name"),
                "member_count": members_count.count or 0,
                "paid_count": paid_count.count or 0,
            })

        return invoices, result.count or 0

    def send_invoice(self, invoice_id: int, org_id: int) -> dict:
        """청구서 발송 (status → sent)"""
        result = self.supabase.table("app_invoices").update({
            "status": InvoiceStatus.sent.value,
            "updated_at": datetime.now().isoformat(),
        }).eq("id", invoice_id).eq("org_id", org_id).eq(
            "status", InvoiceStatus.draft.value
        ).execute()

        if not result.data:
            return None
        return result.data[0]

    def cancel_invoice(self, invoice_id: int, org_id: int) -> bool:
        """청구서 취소"""
        result = self.supabase.table("app_invoices").update({
            "status": InvoiceStatus.cancelled.value,
            "updated_at": datetime.now().isoformat(),
        }).eq("id", invoice_id).eq("org_id", org_id).execute()

        if result.data:
            # 멤버별 청구도 취소
            self.supabase.table("app_invoice_members").update({
                "status": InvoiceMemberStatus.waived.value,
            }).eq("invoice_id", invoice_id).execute()
            return True
        return False

    # ─────────────────────────────────────────
    # 수납 관리
    # ─────────────────────────────────────────

    def record_payment(
        self,
        invoice_member_id: int,
        org_id: int,
        amount: int,
        payment_method: str,
        confirmed_by: Optional[str] = None,
        memo: Optional[str] = None,
        portone_payment_id: Optional[str] = None,
    ) -> dict:
        """수납 기록"""

        # invoice_member 조회
        im_result = self.supabase.table("app_invoice_members").select(
            "*, app_invoices!app_invoice_members_invoice_id_fkey(org_id, title)"
        ).eq("id", invoice_member_id).single().execute()

        if not im_result.data:
            raise ValueError("청구 내역을 찾을 수 없습니다")

        im = im_result.data
        invoice_info = im.get("app_invoices", {}) or {}
        if invoice_info.get("org_id") != org_id:
            raise ValueError("권한이 없습니다")

        # 수납 기록 생성
        payment_data = {
            "invoice_member_id": invoice_member_id,
            "org_id": org_id,
            "amount": amount,
            "payment_method": payment_method,
            "payment_status": PaymentStatus.success.value,
            "confirmed_by": confirmed_by,
            "memo": memo,
            "portone_payment_id": portone_payment_id,
            "paid_at": datetime.now().isoformat(),
        }

        payment_result = self.supabase.table("app_payments").insert(
            payment_data
        ).execute()
        payment = payment_result.data[0]

        # invoice_member 업데이트
        new_paid = (im.get("paid_amount") or 0) + amount
        new_status = InvoiceMemberStatus.paid.value if new_paid >= im["amount"] \
            else InvoiceMemberStatus.partial.value

        self.supabase.table("app_invoice_members").update({
            "paid_amount": new_paid,
            "status": new_status,
            "paid_at": datetime.now().isoformat() if new_status == "paid" else None,
        }).eq("id", invoice_member_id).execute()

        # 청구서 전체 상태 업데이트
        self._update_invoice_status(im["invoice_id"])

        return payment

    def _update_invoice_status(self, invoice_id: int):
        """청구서의 모든 멤버 납부 상태를 확인하고 청구서 상태 갱신"""
        members = self.supabase.table("app_invoice_members").select(
            "status"
        ).eq("invoice_id", invoice_id).execute()

        if not members.data:
            return

        statuses = [m["status"] for m in members.data]
        all_paid = all(s == "paid" for s in statuses)
        any_paid = any(s in ("paid", "partial") for s in statuses)

        if all_paid:
            new_status = InvoiceStatus.paid.value
        elif any_paid:
            new_status = InvoiceStatus.partial.value
        else:
            return  # 아무도 안 냈으면 상태 유지

        self.supabase.table("app_invoices").update({
            "status": new_status,
            "updated_at": datetime.now().isoformat(),
        }).eq("id", invoice_id).execute()

    def get_payment_summary(self, org_id: int) -> dict:
        """수납 현황 요약"""
        # 전체 청구 멤버 조회
        all_im = self.supabase.table("app_invoice_members").select(
            "amount, paid_amount, status, app_invoices!inner(org_id, status, created_at)"
        ).eq("app_invoices.org_id", org_id).neq(
            "app_invoices.status", "cancelled"
        ).execute()

        total_invoiced = 0
        total_paid = 0
        total_pending = 0
        total_overdue = 0
        outstanding_member_ids = set()
        this_month = date.today().strftime("%Y-%m")
        this_month_invoiced = 0
        this_month_collected = 0

        for im in (all_im.data or []):
            total_invoiced += im["amount"]
            total_paid += im.get("paid_amount", 0)

            if im["status"] == "pending":
                total_pending += im["amount"] - (im.get("paid_amount") or 0)
                outstanding_member_ids.add(im.get("member_id"))
            elif im["status"] == "overdue":
                total_overdue += im["amount"] - (im.get("paid_amount") or 0)
                outstanding_member_ids.add(im.get("member_id"))

            inv_info = im.get("app_invoices", {}) or {}
            created = inv_info.get("created_at", "")
            if created.startswith(this_month):
                this_month_invoiced += im["amount"]
                this_month_collected += im.get("paid_amount", 0)

        collection_rate = (total_paid / total_invoiced * 100) if total_invoiced > 0 else 0

        return {
            "total_invoiced": total_invoiced,
            "total_paid": total_paid,
            "total_pending": total_pending,
            "total_overdue": total_overdue,
            "collection_rate": round(collection_rate, 1),
            "this_month_invoiced": this_month_invoiced,
            "this_month_collected": this_month_collected,
            "outstanding_members": len(outstanding_member_ids),
        }

    def get_outstanding_members(self, org_id: int) -> List[dict]:
        """미납 회원 목록"""
        result = self.supabase.rpc("get_outstanding_members", {
            "p_org_id": org_id
        }).execute()

        # RPC가 없으면 직접 쿼리
        if not result.data:
            im_result = self.supabase.table("app_invoice_members").select(
                "member_id, amount, paid_amount, status, "
                "members!app_invoice_members_member_id_fkey(full_name), "
                "app_invoices!inner(org_id, due_date, status)"
            ).eq("app_invoices.org_id", org_id).in_(
                "status", ["pending", "overdue"]
            ).execute()

            # 멤버별 집계
            member_map = {}
            for im in (im_result.data or []):
                mid = im["member_id"]
                member_info = im.get("members", {}) or {}
                inv_info = im.get("app_invoices", {}) or {}

                if mid not in member_map:
                    member_map[mid] = {
                        "member_id": mid,
                        "member_name": member_info.get("full_name", ""),
                        "total_outstanding": 0,
                        "invoice_count": 0,
                        "oldest_due_date": None,
                    }
                outstanding = im["amount"] - (im.get("paid_amount") or 0)
                member_map[mid]["total_outstanding"] += outstanding
                member_map[mid]["invoice_count"] += 1

                due = inv_info.get("due_date")
                if due:
                    current_oldest = member_map[mid]["oldest_due_date"]
                    if current_oldest is None or due < current_oldest:
                        member_map[mid]["oldest_due_date"] = due

            return sorted(
                member_map.values(),
                key=lambda x: x["total_outstanding"],
                reverse=True
            )

        return result.data

    # ─────────────────────────────────────────
    # 비용 템플릿
    # ─────────────────────────────────────────

    def list_fee_templates(self, org_id: int) -> List[dict]:
        result = self.supabase.table("app_fee_templates").select("*").eq(
            "org_id", org_id
        ).eq("is_active", True).order("name").execute()
        return result.data or []

    def create_fee_template(self, org_id: int, **kwargs) -> dict:
        data = {"org_id": org_id, **kwargs}
        result = self.supabase.table("app_fee_templates").insert(data).execute()
        return result.data[0]

    def update_fee_template(self, template_id: int, org_id: int, **kwargs) -> Optional[dict]:
        result = self.supabase.table("app_fee_templates").update(kwargs).eq(
            "id", template_id
        ).eq("org_id", org_id).execute()
        return result.data[0] if result.data else None

    # ─────────────────────────────────────────
    # 정기 청구
    # ─────────────────────────────────────────

    def list_recurring_bills(self, org_id: int) -> List[dict]:
        result = self.supabase.table("app_recurring_bills").select(
            "*, members!app_recurring_bills_member_id_fkey(full_name), "
            "app_billing_keys(id)"
        ).eq("org_id", org_id).eq("is_active", True).execute()

        bills = []
        for b in (result.data or []):
            member_info = b.get("members", {}) or {}
            bills.append({
                **b,
                "member_name": member_info.get("full_name"),
                "has_billing_key": bool(b.get("app_billing_keys")),
            })
        return bills

    def create_recurring_bill(self, org_id: int, **kwargs) -> dict:
        from dateutil.relativedelta import relativedelta
        billing_day = kwargs.get("billing_day", 1)
        today = date.today()
        if today.day >= billing_day:
            next_date = (today.replace(day=1) + relativedelta(months=1)).replace(day=billing_day)
        else:
            next_date = today.replace(day=billing_day)

        data = {
            "org_id": org_id,
            "next_bill_date": next_date.isoformat(),
            **kwargs,
        }
        result = self.supabase.table("app_recurring_bills").insert(data).execute()
        return result.data[0]

    def generate_monthly_invoices(self, org_id: int, created_by: str) -> List[dict]:
        """정기 청구서 일괄 생성 (매월 실행)"""
        today = date.today()

        # 오늘 이전의 next_bill_date가 있는 정기 청구 조회
        recurring = self.supabase.table("app_recurring_bills").select(
            "*, members!app_recurring_bills_member_id_fkey(full_name)"
        ).eq("org_id", org_id).eq("is_active", True).lte(
            "next_bill_date", today.isoformat()
        ).execute()

        created_invoices = []
        for bill in (recurring.data or []):
            member_info = bill.get("members", {}) or {}
            member_name = member_info.get("full_name", "회원")

            title = f"{today.strftime('%Y년 %m월')} {member_name} - "
            if bill["bill_type"] == "monthly_dues":
                title += "월 회비"
            else:
                title += "레슨비"

            invoice = self.create_invoice(
                org_id=org_id,
                created_by=created_by,
                title=title,
                invoice_type=bill["bill_type"],
                total_amount=bill["amount"],
                member_ids=[bill["member_id"]],
                split_type="none",
            )
            created_invoices.append(invoice)

            # next_bill_date 업데이트
            from dateutil.relativedelta import relativedelta
            next_date = today + relativedelta(months=1)
            next_date = next_date.replace(day=min(bill["billing_day"], 28))

            self.supabase.table("app_recurring_bills").update({
                "last_billed_at": datetime.now().isoformat(),
                "next_bill_date": next_date.isoformat(),
            }).eq("id", bill["id"]).execute()

        return created_invoices

    # ─────────────────────────────────────────
    # 빌링키
    # ─────────────────────────────────────────

    def get_billing_key(self, member_id: str, org_id: int) -> Optional[dict]:
        result = self.supabase.table("app_billing_keys").select("*").eq(
            "member_id", member_id
        ).eq("org_id", org_id).eq("is_active", True).execute()
        return result.data[0] if result.data else None

    def register_billing_key(
        self, member_id: str, org_id: int,
        billing_key: str, card_name: Optional[str] = None,
        card_number_masked: Optional[str] = None,
    ) -> dict:
        # 기존 키 비활성화
        self.supabase.table("app_billing_keys").update({
            "is_active": False,
            "deactivated_at": datetime.now().isoformat(),
        }).eq("member_id", member_id).eq("org_id", org_id).eq(
            "is_active", True
        ).execute()

        # 새 키 등록
        result = self.supabase.table("app_billing_keys").insert({
            "member_id": member_id,
            "org_id": org_id,
            "billing_key": billing_key,
            "card_name": card_name,
            "card_number_masked": card_number_masked,
        }).execute()
        return result.data[0]

    def deactivate_billing_key(self, member_id: str, org_id: int) -> bool:
        result = self.supabase.table("app_billing_keys").update({
            "is_active": False,
            "deactivated_at": datetime.now().isoformat(),
        }).eq("member_id", member_id).eq("org_id", org_id).eq(
            "is_active", True
        ).execute()

        # 관련 정기 청구의 auto_pay도 해제
        self.supabase.table("app_recurring_bills").update({
            "auto_pay": False,
            "billing_key_id": None,
        }).eq("member_id", member_id).eq("org_id", org_id).execute()

        return bool(result.data)

    # ─────────────────────────────────────────
    # PortOne V2 연동
    # ─────────────────────────────────────────

    async def verify_portone_payment(
        self,
        payment_id: str,
        invoice_member_id: int,
        org_id: int,
    ) -> dict:
        """PortOne 결제 검증 후 수납 기록

        1. PortOne API로 결제 상태 확인
        2. invoice_member의 금액과 일치하는지 검증
        3. 성공 시 record_payment 호출
        """
        # 1. PortOne 결제 조회
        payment_info = await portone_client.verify_payment(payment_id)

        status = payment_info.get("status")
        if status != "PAID":
            raise ValueError(f"결제가 완료되지 않았습니다 (status={status})")

        paid_amount = payment_info.get("amount", {}).get("total", 0)

        # 2. invoice_member 금액 확인
        im_result = self.supabase.table("app_invoice_members").select(
            "*, app_invoices!app_invoice_members_invoice_id_fkey(org_id)"
        ).eq("id", invoice_member_id).single().execute()

        if not im_result.data:
            raise ValueError("청구 내역을 찾을 수 없습니다")

        im = im_result.data
        invoice_info = im.get("app_invoices", {}) or {}
        if invoice_info.get("org_id") != org_id:
            raise ValueError("권한이 없습니다")

        expected_amount = im["amount"] - (im.get("paid_amount") or 0)
        if paid_amount != expected_amount:
            logger.warning(
                "PortOne 결제 금액 불일치: expected={}, paid={}, payment_id={}",
                expected_amount, paid_amount, payment_id,
            )

        # 3. 수납 기록
        payment = self.record_payment(
            invoice_member_id=invoice_member_id,
            org_id=org_id,
            amount=paid_amount,
            payment_method=PaymentMethod.card.value,
            portone_payment_id=payment_id,
        )

        logger.info(
            "PortOne 결제 검증 완료: payment_id={}, amount={}, invoice_member_id={}",
            payment_id, paid_amount, invoice_member_id,
        )
        return payment

    async def issue_billing_key_portone(
        self,
        member_id: str,
        org_id: int,
        customer_id: str,
        card_number: str,
        expiry: str,
        birth_or_business: str,
        password_two_digits: str,
    ) -> dict:
        """PortOne으로 빌링키 발급 후 DB 저장

        1. PortOne API로 빌링키 발급
        2. register_billing_key로 DB 저장
        """
        # 1. PortOne 빌링키 발급
        result = await portone_client.issue_billing_key(
            customer_id=customer_id,
            card_number=card_number,
            expiry=expiry,
            birth_or_business=birth_or_business,
            password_two_digits=password_two_digits,
        )

        billing_key = result.get("billingKeyInfo", {}).get("billingKey", "")
        if not billing_key:
            raise ValueError("빌링키 발급 실패: 응답에 billingKey가 없습니다")

        card_info = result.get("billingKeyInfo", {}).get("methods", [{}])
        card_name = None
        card_number_masked = None
        if card_info:
            card_detail = card_info[0].get("card", {})
            card_name = card_detail.get("name")
            card_number_masked = card_detail.get("number")

        # 2. DB 저장
        key = self.register_billing_key(
            member_id=member_id,
            org_id=org_id,
            billing_key=billing_key,
            card_name=card_name,
            card_number_masked=card_number_masked,
        )

        logger.info(
            "PortOne 빌링키 발급 완료: member_id={}, card={}",
            member_id, card_number_masked,
        )
        return key

    # ─────────────────────────────────────────
    # 반복 청구 (app_recurring_billing)
    # ─────────────────────────────────────────

    def create_recurring_billing(self, org_id: int, data: dict) -> dict:
        """반복 청구 규칙 생성"""
        from dateutil.relativedelta import relativedelta

        billing_day = data.get("billing_day", 1)
        today = date.today()

        # 다음 청구일 계산
        if today.day >= billing_day:
            next_billing = (today.replace(day=1) + relativedelta(months=1)).replace(
                day=min(billing_day, 28)
            )
        else:
            next_billing = today.replace(day=min(billing_day, 28))

        record = {
            "organization_id": org_id,
            "member_id": data["member_id"],
            "fee_type": data["fee_type"],
            "amount": data["amount"],
            "billing_day": billing_day,
            "is_active": True,
            "next_billing_at": datetime.combine(next_billing, datetime.min.time()).isoformat(),
        }

        result = self.supabase.table("app_recurring_billing").insert(record).execute()
        if not result.data:
            raise ValueError("반복 청구 생성 실패")

        return result.data[0]

    def list_recurring_billings(
        self,
        org_id: int,
        member_id: Optional[str] = None,
        active_only: bool = True,
    ) -> List[dict]:
        """반복 청구 규칙 목록"""
        query = self.supabase.table("app_recurring_billing").select(
            "*, members!app_recurring_billing_member_id_fkey(full_name)"
        ).eq("organization_id", org_id)

        if member_id:
            query = query.eq("member_id", member_id)
        if active_only:
            query = query.eq("is_active", True)

        result = query.order("created_at", desc=True).execute()

        billings = []
        for b in (result.data or []):
            member_info = b.get("members", {}) or {}
            billings.append({
                **b,
                "member_name": member_info.get("full_name"),
            })
        return billings

    def update_recurring_billing(self, billing_id: str, org_id: int, data: dict) -> Optional[dict]:
        """반복 청구 규칙 수정"""
        from dateutil.relativedelta import relativedelta

        update_data = {k: v for k, v in data.items() if v is not None}

        # billing_day 변경 시 next_billing_at 재계산
        if "billing_day" in update_data:
            new_day = update_data["billing_day"]
            today = date.today()
            if today.day >= new_day:
                next_billing = (today.replace(day=1) + relativedelta(months=1)).replace(
                    day=min(new_day, 28)
                )
            else:
                next_billing = today.replace(day=min(new_day, 28))
            update_data["next_billing_at"] = datetime.combine(
                next_billing, datetime.min.time()
            ).isoformat()

        result = self.supabase.table("app_recurring_billing").update(
            update_data
        ).eq("id", billing_id).eq("organization_id", org_id).execute()

        if not result.data:
            return None
        return result.data[0]

    def delete_recurring_billing(self, billing_id: str, org_id: int) -> bool:
        """반복 청구 규칙 비활성화 (soft delete)"""
        result = self.supabase.table("app_recurring_billing").update({
            "is_active": False,
        }).eq("id", billing_id).eq("organization_id", org_id).execute()
        return bool(result.data)

    def run_billing_cycle(self, org_id: int) -> dict:
        """반복 청구 사이클 실행 - 모든 활성 규칙의 due된 건 처리"""
        from dateutil.relativedelta import relativedelta

        now = datetime.now()

        # 활성 규칙 중 next_billing_at <= now인 것들
        result = self.supabase.table("app_recurring_billing").select(
            "*, members!app_recurring_billing_member_id_fkey(full_name)"
        ).eq("organization_id", org_id).eq("is_active", True).lte(
            "next_billing_at", now.isoformat()
        ).execute()

        total_processed = 0
        fees_created = 0
        errors = 0
        details = []

        for billing in (result.data or []):
            total_processed += 1
            member_info = billing.get("members", {}) or {}
            member_name = member_info.get("full_name", "회원")

            try:
                # fees 테이블에 새 청구 레코드 생성
                fee_data = {
                    "organization_id": org_id,
                    "member_id": billing["member_id"],
                    "amount": billing["amount"],
                    "fee_type": billing["fee_type"],
                    "status": "pending",
                    "due_date": now.strftime("%Y-%m-%d"),
                    "description": f"[자동] {member_name} - {billing['fee_type']}",
                }

                fee_result = self.supabase.table("fees").insert(fee_data).execute()

                if fee_result.data:
                    fees_created += 1

                    # billing 규칙 업데이트: last_billed_at, next_billing_at
                    billing_day = billing.get("billing_day", 1)
                    today = date.today()
                    next_date = (today.replace(day=1) + relativedelta(months=1)).replace(
                        day=min(billing_day, 28)
                    )

                    self.supabase.table("app_recurring_billing").update({
                        "last_billed_at": now.isoformat(),
                        "next_billing_at": datetime.combine(
                            next_date, datetime.min.time()
                        ).isoformat(),
                    }).eq("id", billing["id"]).execute()

                    details.append(f"{member_name}: {billing['amount']}원 청구 생성")
                else:
                    errors += 1
                    details.append(f"{member_name}: 청구 생성 실패")

            except Exception as e:
                errors += 1
                details.append(f"{member_name}: 오류 - {str(e)}")
                logger.error(f"반복 청구 실행 실패 (billing_id={billing['id']}): {e}")

        logger.info(
            f"반복 청구 사이클 완료: org={org_id}, 처리={total_processed}, "
            f"생성={fees_created}, 오류={errors}"
        )

        return {
            "total_processed": total_processed,
            "fees_created": fees_created,
            "errors": errors,
            "details": details,
        }

    def detect_overdue_fees(self, org_id: int, days_threshold: int = 7) -> List[dict]:
        """연체 감지 - pending 상태이면서 days_threshold 이상 지난 건"""
        from datetime import timedelta

        threshold_date = (datetime.now() - timedelta(days=days_threshold)).isoformat()

        # pending 상태이고 created_at이 threshold보다 오래된 fees 조회
        result = self.supabase.table("fees").select(
            "*, members!fees_member_id_fkey(full_name, phone, guardian_member_id)"
        ).eq("organization_id", org_id).eq(
            "status", "pending"
        ).lte("created_at", threshold_date).execute()

        alerts = []
        for fee in (result.data or []):
            member_info = fee.get("members", {}) or {}

            # 연체 상태로 업데이트
            self.supabase.table("fees").update({
                "status": "overdue",
            }).eq("id", fee["id"]).execute()

            # 연체 일수 계산
            created = fee.get("created_at", "")
            if created:
                try:
                    created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    days_overdue = (datetime.now(created_dt.tzinfo) - created_dt).days
                except (ValueError, TypeError):
                    days_overdue = days_threshold
            else:
                days_overdue = days_threshold

            # 학부모(보호자) 정보 조회
            parent_name = None
            parent_phone = None
            guardian_id = member_info.get("guardian_member_id")
            if guardian_id:
                parent_result = self.supabase.table("members").select(
                    "full_name, phone"
                ).eq("id", guardian_id).maybe_single().execute()
                if parent_result and parent_result.data:
                    parent_name = parent_result.data.get("full_name")
                    parent_phone = parent_result.data.get("phone")

            alerts.append({
                "member_id": fee["member_id"],
                "member_name": member_info.get("full_name"),
                "fee_id": fee["id"],
                "amount": fee["amount"],
                "due_date": fee.get("due_date"),
                "days_overdue": days_overdue,
                "parent_name": parent_name,
                "parent_phone": parent_phone,
            })

        logger.info(
            f"연체 감지 완료: org={org_id}, 연체건수={len(alerts)}"
        )

        return alerts

    async def send_overdue_notifications(self, org_id: int, alerts: List[dict]) -> dict:
        """연체 알림 발송"""
        from ..notifications.service import notification_service

        sent = 0
        failed = 0

        for alert in alerts:
            member_name = alert.get("member_name", "회원")
            amount = alert.get("amount", 0)
            days = alert.get("days_overdue", 0)

            title = "납부 안내"
            message = (
                f"{member_name}님, 미납 비용이 있습니다. "
                f"금액: {amount:,}원 (연체 {days}일). "
                f"빠른 납부 부탁드립니다."
            )

            # 본인에게 알림
            try:
                await notification_service.send_notification(
                    org_id=org_id,
                    member_id=alert["member_id"],
                    notification_type="billing",
                    title=title,
                    message=message,
                    channels=["fcm", "app"],
                    reference_type="fee",
                    reference_id=alert.get("fee_id"),
                )
                sent += 1
            except Exception as e:
                logger.error(f"연체 알림 발송 실패 (member {alert['member_id']}): {e}")
                failed += 1

            # 학부모(보호자)에게도 알림
            guardian_id = None
            if alert.get("parent_name"):
                # guardian_member_id를 다시 조회
                member_result = self.supabase.table("members").select(
                    "guardian_member_id"
                ).eq("id", alert["member_id"]).maybe_single().execute()
                if member_result and member_result.data:
                    guardian_id = member_result.data.get("guardian_member_id")

            if guardian_id:
                parent_message = (
                    f"자녀({member_name})의 미납 비용이 있습니다. "
                    f"금액: {amount:,}원 (연체 {days}일). "
                    f"확인 부탁드립니다."
                )
                try:
                    await notification_service.send_notification(
                        org_id=org_id,
                        member_id=guardian_id,
                        notification_type="billing",
                        title="자녀 납부 안내",
                        message=parent_message,
                        channels=["fcm", "app"],
                        reference_type="fee",
                        reference_id=alert.get("fee_id"),
                    )
                except Exception as e:
                    logger.error(f"학부모 연체 알림 발송 실패 (guardian {guardian_id}): {e}")

        logger.info(f"연체 알림 발송 완료: org={org_id}, 성공={sent}, 실패={failed}")
        return {"sent": sent, "failed": failed, "total": len(alerts)}

    async def auto_pay_with_billing_key(
        self,
        member_id: str,
        org_id: int,
        invoice_member_id: int,
    ) -> dict:
        """빌링키로 자동결제

        1. 멤버의 활성 빌링키 조회
        2. invoice_member 금액 확인
        3. PortOne 빌링키 결제 호출
        4. 수납 기록
        """
        # 1. 빌링키 조회
        key = self.get_billing_key(member_id, org_id)
        if not key:
            raise ValueError("등록된 빌링키가 없습니다")

        billing_key = key["billing_key"]

        # 2. invoice_member 금액 확인
        im_result = self.supabase.table("app_invoice_members").select(
            "*, app_invoices!app_invoice_members_invoice_id_fkey(org_id, title)"
        ).eq("id", invoice_member_id).single().execute()

        if not im_result.data:
            raise ValueError("청구 내역을 찾을 수 없습니다")

        im = im_result.data
        invoice_info = im.get("app_invoices", {}) or {}
        if invoice_info.get("org_id") != org_id:
            raise ValueError("권한이 없습니다")

        outstanding = im["amount"] - (im.get("paid_amount") or 0)
        if outstanding <= 0:
            raise ValueError("납부할 금액이 없습니다")

        order_name = invoice_info.get("title", "클럽 비용")
        payment_id = f"auto_{org_id}_{invoice_member_id}_{uuid.uuid4().hex[:8]}"

        # 3. PortOne 빌링키 결제
        pay_result = await portone_client.pay_with_billing_key(
            billing_key=billing_key,
            payment_id=payment_id,
            order_name=order_name,
            amount=outstanding,
        )

        pay_status = pay_result.get("payment", {}).get("status", "")
        if pay_status != "PAID":
            raise ValueError(f"자동결제 실패 (status={pay_status})")

        # 4. 수납 기록
        payment = self.record_payment(
            invoice_member_id=invoice_member_id,
            org_id=org_id,
            amount=outstanding,
            payment_method=PaymentMethod.billing_key.value,
            portone_payment_id=payment_id,
        )

        logger.info(
            "빌링키 자동결제 완료: member_id={}, amount={}, payment_id={}",
            member_id, outstanding, payment_id,
        )
        return payment


# 싱글톤
billing_service = BillingService()

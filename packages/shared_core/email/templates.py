"""이메일 HTML 템플릿 (다국어 지원)"""

from typing import Optional

# 다국어 텍스트
EMAIL_TEXTS = {
    "ko": {
        "verification_title": "이메일 인증",
        "verification_greeting": "안녕하세요, <strong>{name}</strong>님!",
        "verification_body": "FencingMind 회원가입을 완료하려면 아래 버튼을 클릭해주세요.",
        "verification_btn": "이메일 인증하기",
        "verification_fallback": "버튼이 작동하지 않으면 아래 링크를 브라우저에 복사해주세요:",
        "verification_expiry": "이 링크는 24시간 동안 유효합니다.",
        "verification_ignore": "본인이 요청하지 않았다면 이 메일을 무시해주세요.",
        "code_title": "인증코드 확인",
        "code_greeting": "안녕하세요{name_suffix}!",
        "code_body": "아래 인증코드를 입력하여 로그인을 완료해주세요.",
        "code_expiry": "이 코드는 <strong>10분간</strong> 유효합니다.",
        "code_ignore": "본인이 요청하지 않았다면 이 메일을 무시해주세요.",
        "welcome_title": "가입을 환영합니다!",
        "welcome_greeting": "안녕하세요, <strong>{name}</strong>님!",
        "welcome_body": "FencingMind에 가입해주셔서 감사합니다.",
        "welcome_cta": "시작하기",
        "welcome_intro": "관심 서비스를 기반으로 시작 가이드를 안내해드립니다:",
        "welcome_intro_default": "이제 펜싱의 모든 데이터를 탐색할 수 있습니다:",
        "welcome_feature_1": "대회 결과 및 선수 프로필",
        "welcome_feature_2": "랭킹 및 통계 분석",
        "welcome_feature_3": "클럽 관리 도구",
        "welcome_tagline": "FencingMind - 세계 최초의 펜싱 AI 데이터 플랫폼",
        "admin_footer": "이 메일은 FencingMind 관리자가 발송한 메일입니다.",
        "admin_greeting": "안녕하세요, <strong>{name}</strong>님.",
        "svc_goto": "바로가기",
        "svc_coming_soon": "서비스는 현재 준비 중입니다.<br>오픈 시 알려드리겠습니다!",
        "broadcast_greeting": "안녕하세요, <strong>{name}</strong>님.",
        "broadcast_footer_reason": "이 메일은 FencingMind 마케팅 정보 수신에 동의하신 회원님께 발송되었습니다.",
        "broadcast_unsubscribe_prefix": "더 이상 수신을 원하지 않으시면 ",
        "broadcast_unsubscribe_link": "수신거부",
        "broadcast_unsubscribe_suffix": "를 눌러주세요.",
    },
    "en": {
        "verification_title": "Email Verification",
        "verification_greeting": "Hello, <strong>{name}</strong>!",
        "verification_body": "Please click the button below to complete your FencingMind registration.",
        "verification_btn": "Verify Email",
        "verification_fallback": "If the button doesn't work, copy and paste this link into your browser:",
        "verification_expiry": "This link is valid for 24 hours.",
        "verification_ignore": "If you didn't request this, please ignore this email.",
        "code_title": "Verification Code",
        "code_greeting": "Hello{name_suffix}!",
        "code_body": "Enter the verification code below to complete your login.",
        "code_expiry": "This code is valid for <strong>10 minutes</strong>.",
        "code_ignore": "If you didn't request this, please ignore this email.",
        "welcome_title": "Welcome!",
        "welcome_greeting": "Hello, <strong>{name}</strong>!",
        "welcome_body": "Thank you for joining FencingMind.",
        "welcome_cta": "Get Started",
        "welcome_intro": "Here's a guide based on your selected services:",
        "welcome_intro_default": "You can now explore all fencing data:",
        "welcome_feature_1": "Competition results & player profiles",
        "welcome_feature_2": "Rankings & statistics",
        "welcome_feature_3": "Club management tools",
        "welcome_tagline": "FencingMind - The World's First AI-Powered Fencing Data Platform",
        "admin_footer": "This email was sent by a FencingMind administrator.",
        "admin_greeting": "Hello, <strong>{name}</strong>.",
        "svc_goto": "Go",
        "svc_coming_soon": "services are currently in preparation.<br>We'll notify you when they launch!",
        "broadcast_greeting": "Hello, <strong>{name}</strong>.",
        "broadcast_footer_reason": "You are receiving this email because you opted in to FencingMind marketing communications.",
        "broadcast_unsubscribe_prefix": "If you no longer wish to receive these emails, please ",
        "broadcast_unsubscribe_link": "unsubscribe",
        "broadcast_unsubscribe_suffix": ".",
    },
}

# 서비스별 소개 정보 (다국어)
SERVICE_DESCRIPTIONS = {
    "data": {
        "icon": "&#128202;",  # 📊
        "name": {"ko": "데이터", "en": "Data"},
        "url": "https://data.fencingmind.ai",
        "features": {
            "ko": ["대회 결과 실시간 업데이트", "선수 프로필 및 전적 분석", "랭킹 및 통계 대시보드"],
            "en": ["Real-time competition results", "Player profiles & match analysis", "Rankings & statistics dashboard"],
        },
    },
    "analytics": {
        "icon": "&#127919;",  # 🎯
        "name": {"ko": "AI분석", "en": "AI Analytics"},
        "features": {
            "ko": ["경기 영상 AI 분석", "기술 개선 리포트", "상대 분석"],
            "en": ["AI video analysis", "Technique improvement reports", "Opponent analysis"],
        },
        "coming_soon": True,
    },
    "shop": {
        "icon": "&#128722;",  # 🛒
        "name": {"ko": "쇼핑", "en": "Shop"},
        "features": {
            "ko": ["펜싱 용품 구매", "인증된 장비 리뷰", "할인 알림"],
            "en": ["Fencing equipment", "Verified gear reviews", "Discount alerts"],
        },
        "coming_soon": True,
    },
    "club": {
        "icon": "&#127979;",  # 🏫
        "name": {"ko": "클럽관리", "en": "Club"},
        "url": "https://club.fencingmind.ai",
        "features": {
            "ko": ["출석 자동 체크인", "레슨 일정 관리", "수강료 관리"],
            "en": ["Auto check-in", "Lesson scheduling", "Fee management"],
        },
    },
    "community": {
        "icon": "&#128172;",  # 💬
        "name": {"ko": "커뮤니티", "en": "Community"},
        "features": {
            "ko": ["펜싱 포럼 참여", "Q&amp;A 질문/답변", "선수/코치 네트워킹"],
            "en": ["Fencing forums", "Q&amp;A", "Player/coach networking"],
        },
        "coming_soon": True,
    },
}


def get_svc_name(svc: dict, lang: str = "ko") -> str:
    """서비스 이름을 언어에 맞게 반환"""
    name = svc.get("name", "")
    if isinstance(name, dict):
        return name.get(lang, name.get("ko", ""))
    return name


def get_svc_features(svc: dict, lang: str = "ko") -> list:
    """서비스 기능 목록을 언어에 맞게 반환"""
    features = svc.get("features", [])
    if isinstance(features, dict):
        return features.get(lang, features.get("ko", []))
    return features


def _build_service_blocks_html(services: list[str], lang: str = "ko") -> str:
    """선택한 서비스별 소개 블록 HTML 생성"""
    t = EMAIL_TEXTS.get(lang, EMAIL_TEXTS["ko"])
    blocks = []
    coming_soon_services = []

    for svc_key in services:
        svc = SERVICE_DESCRIPTIONS.get(svc_key)
        if not svc:
            continue

        if svc.get("coming_soon"):
            coming_soon_services.append(svc)
            continue

        features = get_svc_features(svc, lang)
        features_html = "".join(f"<li>{f}</li>" for f in features)
        url = svc.get("url", "https://data.fencingmind.ai")
        name = get_svc_name(svc, lang)
        blocks.append(f"""
    <div style="background:#f7fafc;border:1px solid #e2e8f0;border-radius:8px;padding:16px;margin-bottom:12px;">
        <h3 style="font-size:16px;color:#333;margin:0 0 8px 0;">{svc["icon"]} {name}</h3>
        <ul style="color:#555;font-size:14px;line-height:1.8;margin:0;padding-left:20px;">{features_html}</ul>
        <div style="margin-top:12px;">
            <a href="{url}" style="display:inline-block;padding:8px 20px;background:#3182ce;color:#fff;text-decoration:none;border-radius:6px;font-size:14px;">{t["svc_goto"]}</a>
        </div>
    </div>""")

    if coming_soon_services:
        names = ", ".join(f'{s["icon"]} {get_svc_name(s, lang)}' for s in coming_soon_services)
        blocks.append(f"""
    <div style="background:#fffbeb;border:1px solid #fef3c7;border-radius:8px;padding:16px;margin-bottom:12px;">
        <p style="color:#92400e;font-size:14px;margin:0;">
            {names} {t["svc_coming_soon"]}
        </p>
    </div>""")

    return "\n".join(blocks)


def get_verification_email_html(name: str, verify_url: str, lang: str = "ko") -> str:
    """이메일 인증 HTML"""
    t = EMAIL_TEXTS.get(lang, EMAIL_TEXTS["ko"])
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f5f7fa;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;margin:40px auto;">
<tr><td style="background:#fff;border-radius:12px;padding:40px;box-shadow:0 2px 12px rgba(0,0,0,0.08);">
    <div style="text-align:center;margin-bottom:32px;">
        <h1 style="color:#3182ce;font-size:24px;margin:0;">FencingMind</h1>
    </div>
    <h2 style="font-size:20px;color:#333;margin-bottom:16px;">{t["verification_title"]}</h2>
    <p style="color:#555;font-size:16px;line-height:1.6;">
        {t["verification_greeting"].format(name=name)}<br>
        {t["verification_body"]}
    </p>
    <div style="text-align:center;margin:32px 0;">
        <a href="{verify_url}" style="display:inline-block;padding:14px 32px;background:#3182ce;color:#fff;text-decoration:none;border-radius:8px;font-size:16px;font-weight:600;">
            {t["verification_btn"]}
        </a>
    </div>
    <p style="color:#888;font-size:13px;line-height:1.5;">
        {t["verification_fallback"]}<br>
        <a href="{verify_url}" style="color:#3182ce;word-break:break-all;">{verify_url}</a>
    </p>
    <hr style="border:none;border-top:1px solid #eee;margin:24px 0;">
    <p style="color:#aaa;font-size:12px;">
        {t["verification_expiry"]}<br>
        {t["verification_ignore"]}
    </p>
</td></tr>
</table>
</body>
</html>"""


def get_welcome_email_html(name: str, services: Optional[list[str]] = None, lang: str = "ko") -> str:
    """환영 이메일 HTML

    Args:
        name: 회원 이름
        services: 선택한 관심 서비스 목록 (None이면 기존 고정 내용 표시)
        lang: 언어 코드 ("ko" 또는 "en")
    """
    t = EMAIL_TEXTS.get(lang, EMAIL_TEXTS["ko"])

    if services:
        service_blocks = _build_service_blocks_html(services, lang=lang)
        intro_text = t["welcome_intro"]
        cta_url = "https://data.fencingmind.ai"
    else:
        # 하위 호환: services 파라미터 없으면 기존 고정 내용
        service_blocks = f"""
    <ul style="color:#555;font-size:15px;line-height:1.8;">
        <li>{t["welcome_feature_1"]}</li>
        <li>{t["welcome_feature_2"]}</li>
        <li>{t["welcome_feature_3"]}</li>
    </ul>"""
        intro_text = t["welcome_intro_default"]
        cta_url = "https://data.fencingmind.ai"

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f5f7fa;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;margin:40px auto;">
<tr><td style="background:#fff;border-radius:12px;padding:40px;box-shadow:0 2px 12px rgba(0,0,0,0.08);">
    <div style="text-align:center;margin-bottom:32px;">
        <h1 style="color:#3182ce;font-size:24px;margin:0;">FencingMind</h1>
    </div>
    <h2 style="font-size:20px;color:#333;margin-bottom:16px;">{t["welcome_title"]}</h2>
    <p style="color:#555;font-size:16px;line-height:1.6;">
        {t["welcome_greeting"].format(name=name)}<br>
        {t["welcome_body"]}
    </p>
    <p style="color:#555;font-size:16px;line-height:1.6;">
        {intro_text}
    </p>
    {service_blocks}
    <div style="text-align:center;margin:32px 0;">
        <a href="{cta_url}" style="display:inline-block;padding:14px 32px;background:#3182ce;color:#fff;text-decoration:none;border-radius:8px;font-size:16px;font-weight:600;">
            {t["welcome_cta"]}
        </a>
    </div>
    <hr style="border:none;border-top:1px solid #eee;margin:24px 0;">
    <p style="color:#aaa;font-size:12px;">
        {t["welcome_tagline"]}
    </p>
</td></tr>
</table>
</body>
</html>"""


def get_verification_code_email_html(name: str, code: str, lang: str = "ko") -> str:
    """이메일 인증코드 HTML"""
    t = EMAIL_TEXTS.get(lang, EMAIL_TEXTS["ko"])

    # 이름 접미사 처리 (한국어: "님", 영어: 없음)
    if name:
        if lang == "ko":
            name_suffix = f", <strong>{name}</strong>님"
        else:
            name_suffix = f", <strong>{name}</strong>"
    else:
        name_suffix = ""

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f5f7fa;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;margin:40px auto;">
<tr><td style="background:#fff;border-radius:12px;padding:40px;box-shadow:0 2px 12px rgba(0,0,0,0.08);">
    <div style="text-align:center;margin-bottom:32px;">
        <h1 style="color:#3182ce;font-size:24px;margin:0;">FencingMind</h1>
    </div>
    <h2 style="font-size:20px;color:#333;margin-bottom:16px;">{t["code_title"]}</h2>
    <p style="color:#555;font-size:16px;line-height:1.6;">
        {t["code_greeting"].format(name_suffix=name_suffix)}<br>
        {t["code_body"]}
    </p>
    <div style="text-align:center;margin:32px 0;">
        <div style="display:inline-block;padding:16px 40px;background:#f7fafc;border:2px solid #3182ce;border-radius:12px;letter-spacing:8px;font-size:32px;font-weight:700;color:#2c5282;">
            {code}
        </div>
    </div>
    <p style="color:#888;font-size:14px;text-align:center;margin-bottom:24px;">
        {t["code_expiry"]}
    </p>
    <hr style="border:none;border-top:1px solid #eee;margin:24px 0;">
    <p style="color:#aaa;font-size:12px;">
        {t["code_ignore"]}<br>
        {t["welcome_tagline"]}
    </p>
</td></tr>
</table>
</body>
</html>"""


def get_admin_email_html(recipient_name: str, subject: str, body: str, lang: str = "ko") -> str:
    """관리자가 회원에게 보내는 이메일 HTML

    Args:
        recipient_name: 수신자 이름
        subject: 제목 (HTML 헤딩에 표시)
        body: 본문 텍스트 (줄바꿈은 <br>로 변환)
        lang: 언어 코드 ("ko" 또는 "en")
    """
    t = EMAIL_TEXTS.get(lang, EMAIL_TEXTS["ko"])
    body_html = body.replace("\n", "<br>")
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f5f7fa;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;margin:40px auto;">
<tr><td style="background:#fff;border-radius:12px;padding:40px;box-shadow:0 2px 12px rgba(0,0,0,0.08);">
    <div style="text-align:center;margin-bottom:32px;">
        <h1 style="color:#3182ce;font-size:24px;margin:0;">FencingMind</h1>
    </div>
    <h2 style="font-size:20px;color:#333;margin-bottom:16px;">{subject}</h2>
    <p style="color:#555;font-size:16px;line-height:1.6;">
        {t["admin_greeting"].format(name=recipient_name)}
    </p>
    <div style="color:#555;font-size:16px;line-height:1.8;margin:16px 0;">
        {body_html}
    </div>
    <hr style="border:none;border-top:1px solid #eee;margin:24px 0;">
    <p style="color:#aaa;font-size:12px;">
        {t["admin_footer"]}<br>
        <a href="mailto:support@fencingmind.ai" style="color:#3182ce;">support@fencingmind.ai</a>
    </p>
</td></tr>
</table>
</body>
</html>"""


def get_broadcast_email_html(
    name: str,
    subject: str,
    body_html: str,
    unsubscribe_url: str,
    lang: str = "ko",
) -> str:
    """관리자 배치 발송(공지/뉴스레터) 이메일 HTML

    기존 관리자 이메일 스타일과 일관되게 렌더링하고, 하단에 마케팅 수신동의
    안내와 필수 수신거부(unsubscribe) 링크를 포함한다.

    Args:
        name: 수신자 이름
        subject: 제목 (HTML 헤딩에 표시)
        body_html: 본문 HTML (관리자가 작성, 그대로 삽입)
        unsubscribe_url: 수신거부 링크 URL
        lang: 언어 코드 ("ko" 또는 "en")
    """
    t = EMAIL_TEXTS.get(lang, EMAIL_TEXTS["ko"])
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f5f7fa;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;margin:40px auto;">
<tr><td style="background:#fff;border-radius:12px;padding:40px;box-shadow:0 2px 12px rgba(0,0,0,0.08);">
    <div style="text-align:center;margin-bottom:32px;">
        <h1 style="color:#3182ce;font-size:24px;margin:0;">FencingMind</h1>
    </div>
    <h2 style="font-size:20px;color:#333;margin-bottom:16px;">{subject}</h2>
    <p style="color:#555;font-size:16px;line-height:1.6;">
        {t["broadcast_greeting"].format(name=name)}
    </p>
    <div style="color:#555;font-size:16px;line-height:1.8;margin:16px 0;">
        {body_html}
    </div>
    <hr style="border:none;border-top:1px solid #eee;margin:24px 0;">
    <p style="color:#aaa;font-size:12px;line-height:1.6;">
        {t["broadcast_footer_reason"]}<br>
        {t["broadcast_unsubscribe_prefix"]}<a href="{unsubscribe_url}" style="color:#3182ce;">{t["broadcast_unsubscribe_link"]}</a>{t["broadcast_unsubscribe_suffix"]}<br>
        {t["welcome_tagline"]}
    </p>
</td></tr>
</table>
</body>
</html>"""

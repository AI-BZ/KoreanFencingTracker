"""
대한펜싱협회 앱 API 역분석 도구

mitmproxy를 사용하여 앱 트래픽을 캡처하고 분석합니다.

사용법:
1. mitmproxy 설치: pip install mitmproxy
2. 프록시 실행: mitmdump -s app_api_analyzer.py -p 8080
3. Android 기기/에뮬레이터에서 프록시 설정 (IP:8080)
4. mitmproxy 인증서 설치: http://mitm.it
5. 대한펜싱협회 앱 실행 및 트래픽 캡처
"""

import json
import os
from datetime import datetime
from mitmproxy import http, ctx
from pathlib import Path


# 캡처할 도메인 목록
TARGET_DOMAINS = [
    "fencing.sports.or.kr",
    "kff.co.kr",
    "sports.or.kr"
]

# 결과 저장 디렉토리
OUTPUT_DIR = Path("captured_apis")
OUTPUT_DIR.mkdir(exist_ok=True)


class KFFAppAnalyzer:
    """대한펜싱협회 앱 API 분석기"""

    def __init__(self):
        self.captured_requests = []
        self.unique_endpoints = set()
        self.session_start = datetime.now().strftime("%Y%m%d_%H%M%S")

    def request(self, flow: http.HTTPFlow) -> None:
        """요청 캡처"""
        if not self._is_target_request(flow):
            return

        request_data = {
            "timestamp": datetime.now().isoformat(),
            "method": flow.request.method,
            "url": flow.request.pretty_url,
            "host": flow.request.host,
            "path": flow.request.path,
            "headers": dict(flow.request.headers),
            "content_type": flow.request.headers.get("Content-Type", ""),
            "body": self._get_body(flow.request),
        }

        self.captured_requests.append(request_data)
        self.unique_endpoints.add(f"{flow.request.method} {flow.request.path}")

        ctx.log.info(f"[KFF] 요청 캡처: {flow.request.method} {flow.request.path}")

    def response(self, flow: http.HTTPFlow) -> None:
        """응답 캡처"""
        if not self._is_target_request(flow):
            return

        # 마지막 요청에 응답 추가
        if self.captured_requests:
            response_data = {
                "status_code": flow.response.status_code,
                "headers": dict(flow.response.headers),
                "content_type": flow.response.headers.get("Content-Type", ""),
                "body": self._get_body(flow.response),
            }
            self.captured_requests[-1]["response"] = response_data

        ctx.log.info(f"[KFF] 응답 캡처: {flow.response.status_code}")

        # 주기적으로 저장
        if len(self.captured_requests) % 10 == 0:
            self._save_results()

    def done(self):
        """분석 완료 시 결과 저장"""
        self._save_results()
        self._generate_report()

    def _is_target_request(self, flow: http.HTTPFlow) -> bool:
        """대상 요청인지 확인"""
        return any(domain in flow.request.host for domain in TARGET_DOMAINS)

    def _get_body(self, message) -> dict:
        """요청/응답 본문 추출"""
        if not message.content:
            return None

        content_type = message.headers.get("Content-Type", "")

        try:
            if "application/json" in content_type:
                return json.loads(message.content)
            elif "application/x-www-form-urlencoded" in content_type:
                # Form data 파싱
                return dict(item.split("=") for item in message.content.decode().split("&") if "=" in item)
            else:
                # 텍스트로 반환
                return {"raw": message.content.decode("utf-8", errors="replace")[:1000]}
        except Exception:
            return {"raw": str(message.content[:500])}

    def _save_results(self):
        """결과 저장"""
        output_file = OUTPUT_DIR / f"captured_{self.session_start}.json"

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump({
                "session_start": self.session_start,
                "unique_endpoints": list(self.unique_endpoints),
                "total_requests": len(self.captured_requests),
                "requests": self.captured_requests
            }, f, ensure_ascii=False, indent=2)

        ctx.log.info(f"[KFF] 결과 저장: {output_file}")

    def _generate_report(self):
        """분석 보고서 생성"""
        report_file = OUTPUT_DIR / f"report_{self.session_start}.md"

        with open(report_file, "w", encoding="utf-8") as f:
            f.write("# 대한펜싱협회 앱 API 분석 보고서\n\n")
            f.write(f"분석 일시: {datetime.now().isoformat()}\n\n")

            f.write("## 발견된 엔드포인트\n\n")
            for endpoint in sorted(self.unique_endpoints):
                f.write(f"- `{endpoint}`\n")

            f.write(f"\n## 총 캡처된 요청: {len(self.captured_requests)}개\n\n")

            # 엔드포인트별 상세
            f.write("## 엔드포인트 상세\n\n")
            endpoint_details = {}
            for req in self.captured_requests:
                key = f"{req['method']} {req['path']}"
                if key not in endpoint_details:
                    endpoint_details[key] = {
                        "count": 0,
                        "sample_request": req.get("body"),
                        "sample_response": req.get("response", {}).get("body")
                    }
                endpoint_details[key]["count"] += 1

            for endpoint, details in endpoint_details.items():
                f.write(f"### {endpoint}\n\n")
                f.write(f"- 호출 횟수: {details['count']}\n")

                if details["sample_request"]:
                    f.write(f"- 요청 샘플:\n```json\n{json.dumps(details['sample_request'], ensure_ascii=False, indent=2)}\n```\n")

                if details["sample_response"]:
                    response_preview = json.dumps(details["sample_response"], ensure_ascii=False, indent=2)
                    if len(response_preview) > 1000:
                        response_preview = response_preview[:1000] + "...(생략)"
                    f.write(f"- 응답 샘플:\n```json\n{response_preview}\n```\n")

                f.write("\n")

        ctx.log.info(f"[KFF] 보고서 생성: {report_file}")


# mitmproxy 애드온 등록
addons = [KFFAppAnalyzer()]


if __name__ == "__main__":
    print("""
대한펜싱협회 앱 API 역분석 도구

사용 방법:
1. mitmproxy 실행:
   mitmdump -s app_api_analyzer.py -p 8080

2. Android 기기/에뮬레이터 설정:
   - WiFi 설정 > 프록시 > 수동
   - 호스트: 컴퓨터 IP 주소
   - 포트: 8080

3. mitmproxy 인증서 설치:
   - 기기에서 http://mitm.it 접속
   - Android 인증서 다운로드 및 설치

4. 대한펜싱협회 앱 실행:
   - 앱에서 다양한 기능 사용
   - API 트래픽 자동 캡처

5. 결과 확인:
   - captured_apis/ 폴더에 JSON 및 보고서 저장

주의사항:
- Android 7.0 이상에서는 앱이 사용자 인증서를 신뢰하지 않을 수 있음
- 이 경우 루팅된 기기 또는 에뮬레이터 필요
- Magisk + LSPosed + TrustMeAlready 모듈 사용 권장
""")

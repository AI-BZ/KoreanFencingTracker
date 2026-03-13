"""이메일 HTML 템플릿"""


def get_verification_email_html(name: str, verify_url: str) -> str:
    """이메일 인증 HTML"""
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f5f7fa;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;margin:40px auto;">
<tr><td style="background:#fff;border-radius:12px;padding:40px;box-shadow:0 2px 12px rgba(0,0,0,0.08);">
    <div style="text-align:center;margin-bottom:32px;">
        <h1 style="color:#3182ce;font-size:24px;margin:0;">FencingMind</h1>
    </div>
    <h2 style="font-size:20px;color:#333;margin-bottom:16px;">이메일 인증</h2>
    <p style="color:#555;font-size:16px;line-height:1.6;">
        안녕하세요, <strong>{name}</strong>님!<br>
        FencingMind 회원가입을 완료하려면 아래 버튼을 클릭해주세요.
    </p>
    <div style="text-align:center;margin:32px 0;">
        <a href="{verify_url}" style="display:inline-block;padding:14px 32px;background:#3182ce;color:#fff;text-decoration:none;border-radius:8px;font-size:16px;font-weight:600;">
            이메일 인증하기
        </a>
    </div>
    <p style="color:#888;font-size:13px;line-height:1.5;">
        버튼이 작동하지 않으면 아래 링크를 브라우저에 복사해주세요:<br>
        <a href="{verify_url}" style="color:#3182ce;word-break:break-all;">{verify_url}</a>
    </p>
    <hr style="border:none;border-top:1px solid #eee;margin:24px 0;">
    <p style="color:#aaa;font-size:12px;">
        이 링크는 24시간 동안 유효합니다.<br>
        본인이 요청하지 않았다면 이 메일을 무시해주세요.
    </p>
</td></tr>
</table>
</body>
</html>"""


def get_welcome_email_html(name: str) -> str:
    """환영 이메일 HTML"""
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f5f7fa;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;margin:40px auto;">
<tr><td style="background:#fff;border-radius:12px;padding:40px;box-shadow:0 2px 12px rgba(0,0,0,0.08);">
    <div style="text-align:center;margin-bottom:32px;">
        <h1 style="color:#3182ce;font-size:24px;margin:0;">FencingMind</h1>
    </div>
    <h2 style="font-size:20px;color:#333;margin-bottom:16px;">가입을 환영합니다!</h2>
    <p style="color:#555;font-size:16px;line-height:1.6;">
        안녕하세요, <strong>{name}</strong>님!<br>
        FencingMind에 가입해주셔서 감사합니다.
    </p>
    <p style="color:#555;font-size:16px;line-height:1.6;">
        이제 펜싱의 모든 데이터를 탐색할 수 있습니다:
    </p>
    <ul style="color:#555;font-size:15px;line-height:1.8;">
        <li>대회 결과 및 선수 프로필</li>
        <li>랭킹 및 통계 분석</li>
        <li>클럽 관리 도구</li>
    </ul>
    <div style="text-align:center;margin:32px 0;">
        <a href="https://data.fencingmind.ai" style="display:inline-block;padding:14px 32px;background:#3182ce;color:#fff;text-decoration:none;border-radius:8px;font-size:16px;font-weight:600;">
            시작하기
        </a>
    </div>
    <hr style="border:none;border-top:1px solid #eee;margin:24px 0;">
    <p style="color:#aaa;font-size:12px;">
        FencingMind - 세계 최초의 펜싱 AI 데이터 플랫폼
    </p>
</td></tr>
</table>
</body>
</html>"""

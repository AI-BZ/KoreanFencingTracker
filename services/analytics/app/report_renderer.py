"""
HTML report renderer for fencing match analysis.

Converts MatchReport dict into standalone HTML with inline CSS,
suitable for browser display and PDF conversion via weasyprint.
"""

from html import escape
from typing import Optional


ACTION_KR = {
    "attack": "공격",
    "riposte": "리포스트",
    "parry": "파리",
    "lunge": "런지",
    "fleche": "플레쉬",
    "retreat": "후퇴",
    "advance": "전진",
    "counter_attack": "콘트르아탁",
    "remise": "르미즈",
    "unknown": "미식별",
}

WEAPON_KR = {
    "foil": "플뢰레",
    "epee": "에페",
    "sabre": "사브르",
}

SEVERITY_STYLE = {
    "info": ("background:#eff6ff;border-left:4px solid #3b82f6;", "#1e40af"),
    "warning": ("background:#fffbeb;border-left:4px solid #f59e0b;", "#92400e"),
    "suggestion": ("background:#f0fdf4;border-left:4px solid #22c55e;", "#166534"),
}

SIDE_KR = {"left": "왼쪽", "right": "오른쪽"}


class ReportRenderer:
    """Renders MatchReport dict to standalone HTML string."""

    def render_html(self, report_dict: dict, standalone: bool = True) -> str:
        """
        Render MatchReport dict to HTML string.

        Args:
            report_dict: MatchReport.to_dict() output
            standalone: If True, include full HTML document with embedded CSS

        Returns:
            HTML string
        """
        summary = report_dict.get("summary", {})
        touches = report_dict.get("touches", [])
        left = report_dict.get("left_fencer")
        right = report_dict.get("right_fencer")
        insights = report_dict.get("insights", [])
        meta = report_dict.get("meta", {})

        parts = []
        parts.append(self._render_summary(summary))
        parts.append(self._render_score_timeline(touches))
        parts.append(self._render_touch_table(touches))
        if left or right:
            parts.append(self._render_fencer_stats(left, right))
        if insights:
            parts.append(self._render_insights(insights))
        parts.append(self._render_meta(meta))

        body = "\n".join(parts)

        if standalone:
            return self._wrap_document(body, summary)
        return body

    # ------------------------------------------------------------------
    # Section renderers
    # ------------------------------------------------------------------

    def _render_summary(self, summary: dict) -> str:
        score = escape(str(summary.get("final_score", "0-0")))
        weapon = summary.get("weapon")
        weapon_label = WEAPON_KR.get(weapon, weapon) if weapon else ""
        duration = escape(str(summary.get("match_duration", "")))
        total_touches = summary.get("total_touches", 0)

        weapon_html = ""
        if weapon_label:
            weapon_html = (
                f'<span style="display:inline-block;background:#dbeafe;color:#1e40af;'
                f'padding:2px 10px;border-radius:9999px;font-size:14px;margin-left:12px;">'
                f"{escape(weapon_label)}</span>"
            )

        return f"""
<div style="background:#fff;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,0.1);padding:24px;margin-bottom:20px;">
  <h2 style="margin:0 0 16px;font-size:20px;color:#111;">경기 요약</h2>
  <div style="display:flex;gap:32px;flex-wrap:wrap;align-items:center;">
    <div style="text-align:center;">
      <div style="font-size:48px;font-weight:700;color:#111;letter-spacing:2px;">{score}</div>
      <div style="font-size:13px;color:#6b7280;margin-top:4px;">최종 스코어{weapon_html}</div>
    </div>
    <div style="display:flex;gap:24px;">
      <div style="text-align:center;">
        <div style="font-size:28px;font-weight:600;color:#374151;">{total_touches}</div>
        <div style="font-size:13px;color:#6b7280;">총 터치</div>
      </div>
      <div style="text-align:center;">
        <div style="font-size:28px;font-weight:600;color:#374151;">{duration}</div>
        <div style="font-size:13px;color:#6b7280;">경기 시간</div>
      </div>
    </div>
  </div>
</div>"""

    def _render_score_timeline(self, touches: list) -> str:
        if not touches:
            return ""

        rows = []
        for t in touches:
            scorer = t.get("scorer", "")
            score_after = escape(str(t.get("score_after", "")))
            match_time = escape(str(t.get("match_time", "")))
            left_marker = "●" if scorer == "left" else ""
            right_marker = "●" if scorer == "right" else ""

            left_style = 'color:#2563eb;font-weight:700;' if scorer == "left" else 'color:#d1d5db;'
            right_style = 'color:#dc2626;font-weight:700;' if scorer == "right" else 'color:#d1d5db;'

            rows.append(
                f"<tr>"
                f'<td style="padding:6px 12px;text-align:center;font-size:13px;color:#6b7280;">{match_time}</td>'
                f'<td style="padding:6px 12px;text-align:center;{left_style}font-size:18px;">{left_marker}</td>'
                f'<td style="padding:6px 12px;text-align:center;font-weight:600;font-size:15px;">{score_after}</td>'
                f'<td style="padding:6px 12px;text-align:center;{right_style}font-size:18px;">{right_marker}</td>'
                f"</tr>"
            )

        return f"""
<div style="background:#fff;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,0.1);padding:24px;margin-bottom:20px;">
  <h2 style="margin:0 0 16px;font-size:20px;color:#111;">스코어 타임라인</h2>
  <table style="width:100%;border-collapse:collapse;">
    <thead>
      <tr style="border-bottom:2px solid #e5e7eb;">
        <th style="padding:8px 12px;text-align:center;font-size:13px;color:#6b7280;font-weight:600;">시간</th>
        <th style="padding:8px 12px;text-align:center;font-size:13px;color:#2563eb;font-weight:600;">왼쪽</th>
        <th style="padding:8px 12px;text-align:center;font-size:13px;color:#6b7280;font-weight:600;">스코어</th>
        <th style="padding:8px 12px;text-align:center;font-size:13px;color:#dc2626;font-weight:600;">오른쪽</th>
      </tr>
    </thead>
    <tbody>
      {"".join(rows)}
    </tbody>
  </table>
</div>"""

    def _render_touch_table(self, touches: list) -> str:
        if not touches:
            return ""

        rows = []
        for t in touches:
            num = t.get("touch_number", "")
            match_time = escape(str(t.get("match_time", "")))
            video_ts = escape(str(t.get("video_timestamp", "")))
            scorer = t.get("scorer", "")
            scorer_kr = SIDE_KR.get(scorer, scorer or "")
            score_after = escape(str(t.get("score_after", "")))

            action = t.get("action_scorer", "unknown") or "unknown"
            action_kr = ACTION_KR.get(action, action)
            conf = t.get("action_confidence", 0)
            conf_pct = f"{conf * 100:.0f}%" if conf else "-"

            opp_action = t.get("action_opponent") or ""
            opp_kr = ACTION_KR.get(opp_action, opp_action) if opp_action else "-"

            scorer_color = "#2563eb" if scorer == "left" else "#dc2626" if scorer == "right" else "#374151"

            rows.append(
                f"<tr style='border-bottom:1px solid #f3f4f6;'>"
                f'<td style="padding:8px 10px;text-align:center;font-size:13px;">{num}</td>'
                f'<td style="padding:8px 10px;text-align:center;font-size:13px;">{match_time}</td>'
                f'<td style="padding:8px 10px;text-align:center;font-size:13px;color:{scorer_color};font-weight:600;">{escape(scorer_kr)}</td>'
                f'<td style="padding:8px 10px;text-align:center;font-size:13px;font-weight:600;">{score_after}</td>'
                f'<td style="padding:8px 10px;text-align:center;font-size:13px;">{escape(action_kr)}</td>'
                f'<td style="padding:8px 10px;text-align:center;font-size:13px;color:#6b7280;">{conf_pct}</td>'
                f'<td style="padding:8px 10px;text-align:center;font-size:13px;">{escape(opp_kr)}</td>'
                f"</tr>"
            )

        return f"""
<div style="background:#fff;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,0.1);padding:24px;margin-bottom:20px;">
  <h2 style="margin:0 0 16px;font-size:20px;color:#111;">터치 상세</h2>
  <table style="width:100%;border-collapse:collapse;">
    <thead>
      <tr style="border-bottom:2px solid #e5e7eb;background:#f9fafb;">
        <th style="padding:8px 10px;text-align:center;font-size:12px;color:#6b7280;font-weight:600;">#</th>
        <th style="padding:8px 10px;text-align:center;font-size:12px;color:#6b7280;font-weight:600;">시간</th>
        <th style="padding:8px 10px;text-align:center;font-size:12px;color:#6b7280;font-weight:600;">득점자</th>
        <th style="padding:8px 10px;text-align:center;font-size:12px;color:#6b7280;font-weight:600;">스코어</th>
        <th style="padding:8px 10px;text-align:center;font-size:12px;color:#6b7280;font-weight:600;">동작</th>
        <th style="padding:8px 10px;text-align:center;font-size:12px;color:#6b7280;font-weight:600;">신뢰도</th>
        <th style="padding:8px 10px;text-align:center;font-size:12px;color:#6b7280;font-weight:600;">상대 동작</th>
      </tr>
    </thead>
    <tbody>
      {"".join(rows)}
    </tbody>
  </table>
</div>"""

    def _render_fencer_stats(self, left: Optional[dict], right: Optional[dict]) -> str:
        cards = []
        for fencer, color, label in [
            (left, "#2563eb", "왼쪽 선수"),
            (right, "#dc2626", "오른쪽 선수"),
        ]:
            if fencer is None:
                continue
            scored = fencer.get("total_touches_scored", 0)
            conceded = fencer.get("total_touches_conceded", 0)
            dist = fencer.get("action_distribution", [])
            top_action = fencer.get("most_common_action", "unknown") or "unknown"
            top_pct = fencer.get("most_common_action_pct", 0)

            bar_rows = []
            for d in dist:
                act = d.get("action", "unknown")
                act_kr = ACTION_KR.get(act, act)
                pct = d.get("percentage", 0)
                cnt = d.get("count", 0)
                bar_width = max(pct, 2)
                bar_rows.append(
                    f'<div style="display:flex;align-items:center;margin-bottom:6px;">'
                    f'<div style="width:80px;font-size:13px;color:#374151;">{escape(act_kr)}</div>'
                    f'<div style="flex:1;background:#f3f4f6;border-radius:4px;height:20px;margin:0 8px;">'
                    f'<div style="width:{bar_width}%;background:{color};border-radius:4px;height:20px;'
                    f'min-width:2px;"></div>'
                    f'</div>'
                    f'<div style="width:60px;font-size:12px;color:#6b7280;text-align:right;">'
                    f'{cnt}회 ({pct:.0f}%)</div>'
                    f'</div>'
                )

            cards.append(f"""
<div style="flex:1;min-width:280px;background:#fff;border-radius:8px;
  box-shadow:0 1px 3px rgba(0,0,0,0.1);padding:20px;border-top:3px solid {color};">
  <h3 style="margin:0 0 12px;font-size:17px;color:{color};">{escape(label)}</h3>
  <div style="display:flex;gap:16px;margin-bottom:16px;">
    <div style="text-align:center;flex:1;">
      <div style="font-size:24px;font-weight:700;color:#111;">{scored}</div>
      <div style="font-size:12px;color:#6b7280;">득점</div>
    </div>
    <div style="text-align:center;flex:1;">
      <div style="font-size:24px;font-weight:700;color:#111;">{conceded}</div>
      <div style="font-size:12px;color:#6b7280;">실점</div>
    </div>
    <div style="text-align:center;flex:1;">
      <div style="font-size:14px;font-weight:600;color:#111;">{escape(ACTION_KR.get(top_action, top_action))}</div>
      <div style="font-size:12px;color:#6b7280;">주요 동작 ({top_pct:.0f}%)</div>
    </div>
  </div>
  <div style="margin-top:8px;">
    <div style="font-size:13px;font-weight:600;color:#374151;margin-bottom:8px;">동작 분포</div>
    {"".join(bar_rows)}
  </div>
</div>""")

        return f"""
<div style="display:flex;gap:20px;flex-wrap:wrap;margin-bottom:20px;">
  {"".join(cards)}
</div>"""

    def _render_insights(self, insights: list) -> str:
        cards = []
        for ins in insights:
            severity = ins.get("severity", "info")
            bg_style, text_color = SEVERITY_STYLE.get(severity, SEVERITY_STYLE["info"])
            target = ins.get("target", "")
            target_kr = SIDE_KR.get(target, target)
            category = ins.get("category", "")
            message = escape(str(ins.get("message", "")))
            evidence = escape(str(ins.get("evidence", "")))

            severity_label = {"info": "정보", "warning": "주의", "suggestion": "제안"}.get(severity, severity)

            cards.append(
                f'<div style="{bg_style}padding:16px;border-radius:6px;margin-bottom:10px;">'
                f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">'
                f'<span style="font-size:12px;font-weight:600;color:{text_color};text-transform:uppercase;">'
                f'{escape(severity_label)} — {escape(target_kr)}</span>'
                f'<span style="font-size:11px;color:#9ca3af;">{escape(category)}</span>'
                f'</div>'
                f'<div style="font-size:14px;color:#111;margin-bottom:4px;">{message}</div>'
                f'<div style="font-size:12px;color:#6b7280;">근거: {evidence}</div>'
                f'</div>'
            )

        return f"""
<div style="background:#fff;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,0.1);padding:24px;margin-bottom:20px;">
  <h2 style="margin:0 0 16px;font-size:20px;color:#111;">코칭 인사이트</h2>
  {"".join(cards)}
</div>"""

    def _render_meta(self, meta: dict) -> str:
        phase = meta.get("phase", "")
        pose_model = escape(str(meta.get("pose_model", "")))
        action_model = escape(str(meta.get("action_model", "")))

        return f"""
<div style="margin-top:24px;padding:12px 16px;background:#f9fafb;border-radius:6px;
  font-size:12px;color:#9ca3af;text-align:center;">
  FencingMind Analytics &middot; Phase {phase} &middot; Pose: {pose_model} &middot; Action: {action_model}
</div>"""

    # ------------------------------------------------------------------
    # Document wrapper
    # ------------------------------------------------------------------

    def _wrap_document(self, body: str, summary: dict) -> str:
        score = escape(str(summary.get("final_score", "")))
        weapon = summary.get("weapon")
        weapon_kr = WEAPON_KR.get(weapon, "") if weapon else ""
        title_parts = ["FencingMind 경기 분석"]
        if weapon_kr:
            title_parts.append(weapon_kr)
        if score:
            title_parts.append(score)
        title = escape(" — ".join(title_parts))

        return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  @page {{
    size: A4 portrait;
    margin: 15mm;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans KR", sans-serif;
    background: #f3f4f6;
    color: #111827;
    line-height: 1.5;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }}
  .container {{
    max-width: 800px;
    margin: 0 auto;
    padding: 24px 16px;
  }}
  .header {{
    text-align: center;
    margin-bottom: 24px;
  }}
  .header h1 {{
    font-size: 24px;
    font-weight: 700;
    color: #111827;
  }}
  .header p {{
    font-size: 13px;
    color: #9ca3af;
    margin-top: 4px;
  }}
  @media print {{
    body {{ background: #fff; }}
    .container {{ padding: 0; }}
  }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>FencingMind 경기 분석 리포트</h1>
    <p>AI 기반 펜싱 경기 영상 분석</p>
  </div>
{body}
</div>
</body>
</html>"""

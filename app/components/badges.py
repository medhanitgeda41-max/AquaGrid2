"""Industrial SCADA styling and actor/status badge helpers (LLM / CODE / HUMAN)."""
from datetime import datetime, timedelta, timezone
import html
from zoneinfo import ZoneInfo
import streamlit as st

try:
    DUBAI_TZ = ZoneInfo("Asia/Dubai")
except Exception:
    # Asia/Dubai is fixed UTC+4 year-round (no DST)
    DUBAI_TZ = timezone(timedelta(hours=4))


def format_dubai_time(ts: str | None) -> str:
    """Convert SQLite UTC timestamp ('YYYY-MM-DD HH:MM:SS') to Asia/Dubai local time (UTC+4)."""
    if not ts:
        return "-"
    raw = str(ts).strip()
    if not raw or raw == "-":
        return "-"
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            dt_utc = datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
            dt_local = dt_utc.astimezone(DUBAI_TZ)
            return dt_local.strftime("%Y-%m-%d %H:%M:%S GST")
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(DUBAI_TZ).strftime("%Y-%m-%d %H:%M:%S GST")
    except ValueError:
        return raw

SCADA_CSS = """
<style>
    .block-container {
        padding-top: 1.2rem;
        padding-bottom: 2rem;
        max-width: 1400px;
    }
    .scada-banner {
        background: linear-gradient(90deg, #0F1C33 0%, #162947 65%, #0D223B 100%);
        border: 1px solid #264269;
        border-left: 5px solid #00C2FF;
        border-radius: 8px;
        padding: 1rem 1.25rem;
        margin-bottom: 1rem;
    }
    .scada-title {
        font-size: 1.45rem;
        font-weight: 700;
        letter-spacing: 0.04em;
        color: #F0F6FC;
        margin: 0;
    }
    .scada-subtitle {
        font-size: 0.88rem;
        color: #9FB3C8;
        margin: 0.2rem 0 0 0;
    }
    .scada-card {
        background: #111B2E;
        border: 1px solid #243757;
        border-radius: 8px;
        padding: 0.95rem 1.1rem;
        margin-bottom: 0.85rem;
    }
    .scada-card-alert {
        background: #1F1420;
        border: 1px solid #7C2D3D;
        border-left: 5px solid #FF4B4B;
        border-radius: 8px;
        padding: 0.95rem 1.1rem;
        margin-bottom: 0.85rem;
    }
    .scada-card-pending {
        background: #1D1B12;
        border: 1px solid #7A5C1B;
        border-left: 5px solid #F59E0B;
        border-radius: 8px;
        padding: 1rem 1.15rem;
        margin-bottom: 0.9rem;
    }
    .scada-card-ok {
        background: #0F211B;
        border: 1px solid #1E5A44;
        border-left: 5px solid #10B981;
        border-radius: 8px;
        padding: 0.95rem 1.1rem;
        margin-bottom: 0.85rem;
    }
    .scada-section-hdr {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        font-size: 0.95rem;
        font-weight: 700;
        letter-spacing: 0.04em;
        text-transform: uppercase;
        color: #D6E4F0;
        margin-bottom: 0.45rem;
    }
    .ag-badge {
        display: inline-block;
        padding: 0.14rem 0.52rem;
        border-radius: 999px;
        font-size: 0.72rem;
        font-weight: 700;
        letter-spacing: 0.05em;
        text-transform: uppercase;
        vertical-align: middle;
        margin-right: 0.25rem;
    }
    .ag-badge-llm {
        background: #3B1D60;
        color: #E2C6FF;
        border: 1px solid #7E4AC2;
    }
    .ag-badge-code {
        background: #0E3A4A;
        color: #7CE8FF;
        border: 1px solid #1E82A8;
    }
    .ag-badge-human {
        background: #4A320C;
        color: #FDE68A;
        border: 1px solid #D97706;
    }
    .ag-badge-ok {
        background: #0F3D2E;
        color: #6EE7B7;
        border: 1px solid #10B981;
    }
    .ag-badge-warn {
        background: #4A320C;
        color: #FCD34D;
        border: 1px solid #F59E0B;
    }
    .ag-badge-danger {
        background: #4C151F;
        color: #FCA5A5;
        border: 1px solid #EF4444;
    }
    .ag-badge-neutral {
        background: #1F2D46;
        color: #CBD5E1;
        border: 1px solid #475569;
    }
    .ag-mono {
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
        font-size: 0.84rem;
    }
    .scada-table {
        width: 100%;
        border-collapse: collapse;
        background: #111B2E;
        border: 1px solid #243757;
        border-radius: 8px;
        overflow: hidden;
        font-size: 0.84rem;
    }
    .scada-table th {
        background: #182742;
        color: #CBD5E1;
        text-align: left;
        padding: 0.5rem 0.65rem;
        border-bottom: 1px solid #2B4166;
        white-space: nowrap;
    }
    .scada-table td {
        padding: 0.5rem 0.65rem;
        border-bottom: 1px solid #1E2E4A;
        color: #E6EDF7;
        vertical-align: top;
        white-space: normal;
        word-wrap: break-word;
        overflow-wrap: anywhere;
    }
</style>
"""


def inject_scada_css() -> None:
    """Inject industrial dark-mode SCADA styles into Streamlit page."""
    st.markdown(SCADA_CSS, unsafe_allow_html=True)


def actor_badge(actor: str) -> str:
    """Return HTML badge showing whether a step was done by LLM, CODE, or HUMAN."""
    norm = (actor or "").strip().upper()
    if norm in ("LLM", "LLM_AGENT"):
        return '<span class="ag-badge ag-badge-llm">LLM</span>'
    if norm in ("CODE", "CODE_GUARD"):
        return '<span class="ag-badge ag-badge-code">CODE</span>'
    if norm in ("HUMAN", "HUMAN_OPERATOR"):
        return '<span class="ag-badge ag-badge-human">HUMAN</span>'
    return f'<span class="ag-badge ag-badge-neutral">{html.escape(norm or "SYSTEM")}</span>'


def status_badge(status: str) -> str:
    """Return color-coded HTML status badge."""
    s = (status or "UNKNOWN").strip().upper()
    if s in ("VALID", "EXECUTED", "APPROVED", "ALLOWED", "COMPLETED", "OPEN", "ONLINE", "NORMAL"):
        cls = "ag-badge-ok"
    elif s in ("PENDING", "STAGED_PENDING_APPROVAL", "AWAITING_HUMAN_APPROVAL", "THROTTLED", "REJECTED_DUPLICATE_PENDING"):
        cls = "ag-badge-warn"
    elif s in (
        "REJECTED_BY_CODE",
        "REJECTED_BY_SAFETY_GUARD",
        "REJECTED_INVALID_TARGET",
        "CANCELLED_BY_SAFETY_RECHECK",
        "ABORTED_BY_SAFETY",
        "REJECTED",
        "REFUSED",
        "BLOCKED",
        "QUARANTINED",
        "CONFIRMED_PIPE_LEAK",
        "CLOSED",
    ):
        cls = "ag-badge-danger"
    else:
        cls = "ag-badge-neutral"
    return f'<span class="ag-badge {cls}">{html.escape(s)}</span>'


def section_header(title: str, actors: list[str], extra_badge: str = "") -> None:
    """Render a consistent SCADA section header with LLM / CODE / HUMAN badges."""
    badges_html = "".join(actor_badge(a) for a in actors)
    st.markdown(
        f'<div class="scada-section-hdr">{badges_html}<span>{html.escape(title)}</span>{extra_badge}</div>',
        unsafe_allow_html=True,
    )

"""Dependency-free Prometheus text metrics for the reference build."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from aijaa.core import tables as t


async def render_metrics(s: AsyncSession) -> str:
    lines = [
        "# HELP aijaa_applications_total Applications by status.",
        "# TYPE aijaa_applications_total gauge",
    ]
    for status, count in (
        await s.execute(select(t.ApplicationRow.status, func.count()).group_by(t.ApplicationRow.status))
    ).all():
        lines.append(f'aijaa_applications_total{{status="{status}"}} {count}')

    lines.extend([
        "# HELP aijaa_tasks_total Tasks by status.",
        "# TYPE aijaa_tasks_total gauge",
    ])
    for status, count in (
        await s.execute(select(t.TaskRow.status, func.count()).group_by(t.TaskRow.status))
    ).all():
        lines.append(f'aijaa_tasks_total{{status="{status}"}} {count}')

    lines.extend([
        "# HELP aijaa_audit_events_total Append-only audit events.",
        "# TYPE aijaa_audit_events_total counter",
    ])
    audit_count = (await s.execute(select(func.count()).select_from(t.AuditRow))).scalar_one()
    lines.append(f"aijaa_audit_events_total {audit_count}")

    lines.extend([
        "# HELP aijaa_llm_tokens_total LLM tokens by direction.",
        "# TYPE aijaa_llm_tokens_total counter",
    ])
    input_tokens, output_tokens = (
        await s.execute(
            select(func.sum(t.LLMUsageRow.input_tokens), func.sum(t.LLMUsageRow.output_tokens))
        )
    ).one()
    lines.append(f'aijaa_llm_tokens_total{{direction="input"}} {input_tokens or 0}')
    lines.append(f'aijaa_llm_tokens_total{{direction="output"}} {output_tokens or 0}')
    return "\n".join(lines) + "\n"

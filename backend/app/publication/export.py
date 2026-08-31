from io import BytesIO

import xlsxwriter
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.spreadsheet import excel_safe_value
from app.publication.errors import format_publication_error
from app.persistence import (
    DraftBatch,
    Job,
    JobItem,
    MercadoLibreAccount,
    ProductMaster,
    ProductVersion,
    Publication,
    PublicationDraft,
)





def _commercial_label(draft: PublicationDraft) -> str:
    commercial = draft.commercial_config or {}
    return str(
        commercial.get("commercial_label")
        or commercial.get("commercial_intent")
        or commercial.get("listing_type_name")
        or ""
    )


def build_job_export_xlsx(db: Session, job: Job) -> bytes:
    """Build the operational handoff workbook for a finished publication job."""
    items = db.scalars(
        select(JobItem).where(JobItem.job_id == job.id).order_by(JobItem.id)
    ).all()

    published_rows: list[list] = []
    error_rows: list[list] = []

    for job_item in items:
        draft = db.get(PublicationDraft, job_item.draft_id)
        if not draft:
            continue
        batch = db.get(DraftBatch, draft.batch_id)
        version = db.get(ProductVersion, batch.product_version_id) if batch else None
        master = db.get(ProductMaster, version.product_master_id) if version else None
        account = db.get(MercadoLibreAccount, batch.account_id) if batch else None
        publication = db.scalar(select(Publication).where(Publication.draft_id == draft.id))

        sku = master.internal_sku if master else ""
        account_name = account.nickname if account else ""
        commercial = draft.commercial_config or {}
        commercial_label = _commercial_label(draft)
        listing_type_id = str(commercial.get("listing_type_id") or "")
        if publication and publication.item_id:
            external = publication.external_response or {}
            published_rows.append(
                [
                    sku,
                    publication.item_id,
                    draft.title,
                    external.get("title") or "",
                    commercial_label,
                    listing_type_id,
                    publication.user_product_id or external.get("user_product_id") or "",
                    account_name,
                    publication.status,
                    publication.published_at,
                ]
            )
        else:
            error_rows.append(
                [
                    sku,
                    draft.sequence_number,
                    draft.title,
                    commercial_label,
                    listing_type_id,
                    account_name,
                    job_item.status,
                    format_publication_error(job_item.last_error or draft.last_error),
                ]
            )

    output = BytesIO()
    workbook = xlsxwriter.Workbook(output, {"in_memory": True})
    header = workbook.add_format(
        {
            "bold": True,
            "font_color": "#FFFFFF",
            "bg_color": "#0D1B3A",
            "border": 0,
            "valign": "vcenter",
        }
    )
    date_fmt = workbook.add_format({"num_format": "yyyy-mm-dd hh:mm"})
    wrap = workbook.add_format({"text_wrap": True, "valign": "top"})

    published = workbook.add_worksheet("Publicaciones")
    headers = [
        "SKU",
        "MLA",
        "Título solicitado",
        "Título devuelto por ML",
        "Cuotas",
        "Listing type",
        "User Product ID",
        "Cuenta",
        "Estado",
        "Fecha publicación",
    ]
    for col, value in enumerate(headers):
        published.write(0, col, value, header)
    for row_index, row in enumerate(published_rows, start=1):
        for col_index, value in enumerate(row):
            fmt = date_fmt if col_index == 9 and value is not None else (wrap if col_index in {2, 3} else None)
            published.write(
                row_index, col_index, excel_safe_value(value, get_settings().app_timezone), fmt
            )
    published.freeze_panes(1, 0)
    published.autofilter(0, 0, max(len(published_rows), 1), len(headers) - 1)
    published.set_column("A:B", 18)
    published.set_column("C:D", 58)
    published.set_column("E:F", 20)
    published.set_column("G:I", 20)
    published.set_column("J:J", 20)
    published.set_row(0, 24)

    errors = workbook.add_worksheet("No publicadas")
    error_headers = ["SKU", "Borrador", "Título", "Cuotas", "Listing type", "Cuenta", "Estado", "Detalle"]
    for col, value in enumerate(error_headers):
        errors.write(0, col, value, header)
    for row_index, row in enumerate(error_rows, start=1):
        for col_index, value in enumerate(row):
            fmt = wrap if col_index in {2, 7} else None
            errors.write(row_index, col_index, value, fmt)
    errors.freeze_panes(1, 0)
    errors.autofilter(0, 0, max(len(error_rows), 1), len(error_headers) - 1)
    errors.set_column("A:B", 18)
    errors.set_column("C:C", 58)
    errors.set_column("D:G", 20)
    errors.set_column("H:H", 70)
    errors.set_row(0, 24)

    workbook.close()
    return output.getvalue()

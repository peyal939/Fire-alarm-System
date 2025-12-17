from __future__ import annotations

import io
import logging
from decimal import Decimal
from typing import TYPE_CHECKING

from django.conf import settings
from django.core.files.base import ContentFile
from django.utils import timezone

if TYPE_CHECKING:
    from .models import Invoice

logger = logging.getLogger(__name__)


def generate_invoice_pdf(invoice: "Invoice") -> bytes:
    """
    Generate a PDF invoice using reportlab.

    Returns the PDF as bytes.
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        SimpleDocTemplate,
        Paragraph,
        Spacer,
        Table,
        TableStyle,
    )

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=20 * mm,
        leftMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
    )

    styles = getSampleStyleSheet()
    story = []

    # Custom styles
    title_style = ParagraphStyle(
        "CustomTitle",
        parent=styles["Heading1"],
        fontSize=24,
        spaceAfter=10,
    )
    heading_style = ParagraphStyle(
        "CustomHeading",
        parent=styles["Heading2"],
        fontSize=14,
        spaceAfter=6,
    )
    normal_style = styles["Normal"]

    # Company Header
    company_name = getattr(settings, "COMPANY_NAME", "Pranisheba Fire Alarm")
    company_address = getattr(
        settings, "COMPANY_ADDRESS", "Dhaka, Bangladesh"
    )
    company_phone = getattr(settings, "COMPANY_PHONE", "")
    company_email = getattr(settings, "COMPANY_EMAIL", "")

    story.append(Paragraph(company_name, title_style))
    story.append(Paragraph(company_address, normal_style))
    if company_phone:
        story.append(Paragraph(f"Phone: {company_phone}", normal_style))
    if company_email:
        story.append(Paragraph(f"Email: {company_email}", normal_style))
    story.append(Spacer(1, 10 * mm))

    # Invoice Header
    story.append(Paragraph(f"INVOICE", title_style))
    story.append(Spacer(1, 5 * mm))

    # Invoice Details Table
    invoice_info = [
        ["Invoice Number:", invoice.number],
        ["Issue Date:", timezone.localtime(invoice.issued_at).strftime("%d %B %Y")],
        ["Status:", invoice.get_status_display()],
    ]
    if invoice.paid_at:
        invoice_info.append(
            ["Paid Date:", timezone.localtime(invoice.paid_at).strftime("%d %B %Y")]
        )

    info_table = Table(invoice_info, colWidths=[40 * mm, 80 * mm])
    info_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    story.append(info_table)
    story.append(Spacer(1, 10 * mm))

    # Customer Details
    story.append(Paragraph("Bill To:", heading_style))
    user = invoice.user
    customer_name = ""
    customer_email = ""
    customer_phone = ""
    customer_address = ""

    if invoice.order:
        customer_name = invoice.order.customer_name or ""
        customer_email = invoice.order.customer_email or ""
        customer_phone = invoice.order.customer_phone or ""
        customer_address = invoice.order.customer_address or ""

    if not customer_name and user:
        customer_name = getattr(user, "full_name", "") or getattr(user, "email", "")
    if not customer_email and user:
        customer_email = getattr(user, "email", "")
    if not customer_phone and user:
        customer_phone = getattr(user, "phone_number", "")
    if not customer_address and user:
        customer_address = getattr(user, "address", "")

    if customer_name:
        story.append(Paragraph(customer_name, normal_style))
    if customer_email:
        story.append(Paragraph(customer_email, normal_style))
    if customer_phone:
        story.append(Paragraph(customer_phone, normal_style))
    if customer_address:
        story.append(Paragraph(customer_address, normal_style))

    story.append(Spacer(1, 10 * mm))

    # Line Items Table
    story.append(Paragraph("Items:", heading_style))

    # Table header
    table_data = [["Description", "Qty", "Unit Price", "Total"]]

    # Add line items
    line_items = invoice.line_items.all()
    for item in line_items:
        table_data.append(
            [
                item.description,
                str(item.quantity),
                f"{invoice.order.currency if invoice.order else 'BDT'} {item.unit_price:,.2f}",
                f"{invoice.order.currency if invoice.order else 'BDT'} {item.total:,.2f}",
            ]
        )

    # Create table
    items_table = Table(
        table_data, colWidths=[80 * mm, 20 * mm, 35 * mm, 35 * mm]
    )
    items_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 10),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
                ("BACKGROUND", (0, 1), (-1, -1), colors.white),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 1), (-1, -1), 9),
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(items_table)
    story.append(Spacer(1, 5 * mm))

    # Totals
    currency = invoice.order.currency if invoice.order else "BDT"
    totals_data = [
        ["Subtotal:", f"{currency} {invoice.subtotal:,.2f}"],
        ["Tax:", f"{currency} {invoice.tax:,.2f}"],
        ["Total:", f"{currency} {invoice.total:,.2f}"],
    ]

    totals_table = Table(totals_data, colWidths=[130 * mm, 40 * mm])
    totals_table.setStyle(
        TableStyle(
            [
                ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("LINEABOVE", (0, -1), (-1, -1), 1, colors.black),
            ]
        )
    )
    story.append(totals_table)
    story.append(Spacer(1, 15 * mm))

    # Notes
    if invoice.notes:
        story.append(Paragraph("Notes:", heading_style))
        story.append(Paragraph(invoice.notes, normal_style))
        story.append(Spacer(1, 10 * mm))

    # Footer
    footer_text = "Thank you for your business!"
    story.append(Paragraph(footer_text, ParagraphStyle(
        "Footer",
        parent=normal_style,
        alignment=1,  # Center
        textColor=colors.grey,
    )))

    # Build PDF
    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()

    return pdf_bytes


def save_invoice_pdf(invoice: "Invoice") -> str:
    """
    Generate and save PDF to the invoice's pdf_file field.

    Returns the file path.
    """
    pdf_bytes = generate_invoice_pdf(invoice)
    filename = f"invoice_{invoice.number}.pdf"

    # Save to model
    invoice.pdf_file.save(filename, ContentFile(pdf_bytes), save=True)

    logger.info("Generated PDF for invoice %s", invoice.number)
    return invoice.pdf_file.name


def create_invoice_for_order(order) -> "Invoice":
    """
    Create an invoice for a paid order.

    Returns the created Invoice instance.
    """
    from .models import Invoice, InvoiceLineItem
    from .enums import InvoiceStatus

    # Generate invoice number
    invoice_number = Invoice.generate_invoice_number()

    # Calculate totals
    subtotal = order.amount or Decimal("0.00")
    tax = Decimal("0.00")  # No tax calculation for now
    total = subtotal + tax

    # Create invoice
    invoice = Invoice.objects.create(
        number=invoice_number,
        user=order.user,
        order=order,
        subtotal=subtotal,
        tax=tax,
        total=total,
        status=InvoiceStatus.PAID if order.order_status == "paid" else InvoiceStatus.DRAFT,
        paid_at=timezone.now() if order.order_status == "paid" else None,
    )

    # Create line items
    package = order.package
    price_per_device = package.price_per_device or Decimal("0")
    mrf = package.mrf or Decimal("0")

    # Device purchase line
    if price_per_device > 0:
        InvoiceLineItem.objects.create(
            invoice=invoice,
            description=f"{package.name} - Device Purchase",
            quantity=order.quantity,
            unit_price=price_per_device,
            total=price_per_device * order.quantity,
        )

    # MRF line (first month) - only for master devices
    if mrf > 0 and order.number_of_master_devices > 0:
        InvoiceLineItem.objects.create(
            invoice=invoice,
            description=f"{package.name} - Monthly Service Fee (1st Month)",
            quantity=order.number_of_master_devices,
            unit_price=mrf,
            total=mrf * order.number_of_master_devices,
        )

    logger.info("Created invoice %s for order %s", invoice.number, order.pk)
    return invoice


def create_invoice_for_subscription_charge(charge) -> "Invoice":
    """
    Create an invoice for a subscription charge.

    Returns the created Invoice instance.
    """
    from .models import Invoice, InvoiceLineItem
    from .enums import InvoiceStatus

    subscription = charge.subscription
    device = subscription.device

    # Generate invoice number
    invoice_number = Invoice.generate_invoice_number()

    # Calculate totals
    subtotal = charge.amount or Decimal("0.00")
    tax = Decimal("0.00")
    total = subtotal + tax

    # Determine status
    from .enums import SubscriptionChargeStatus
    if charge.status == SubscriptionChargeStatus.PAID:
        invoice_status = InvoiceStatus.PAID
        paid_at = timezone.now()
    else:
        invoice_status = InvoiceStatus.DRAFT
        paid_at = None

    # Create invoice
    invoice = Invoice.objects.create(
        number=invoice_number,
        user=device.user,
        subscription_charge=charge,
        subtotal=subtotal,
        tax=tax,
        total=total,
        status=invoice_status,
        paid_at=paid_at,
    )

    # Create line item
    device_name = device.device_name or device.hardware_identifier
    period_start = timezone.localtime(charge.period_start).strftime("%d %b %Y")
    period_end = timezone.localtime(charge.period_end).strftime("%d %b %Y")

    InvoiceLineItem.objects.create(
        invoice=invoice,
        description=f"Subscription - {device_name} ({period_start} to {period_end})",
        quantity=charge.cycles,
        unit_price=subscription.monthly_amount,
        total=charge.amount,
    )

    logger.info("Created invoice %s for subscription charge %s", invoice.number, charge.pk)
    return invoice

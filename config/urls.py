from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView

from core.services.shopify import shopify_webhook_view
from core.views.adjust import adjust_inventory
from core.views.audit import audit_log, webhook_event_log
from core.views.forecast import forecast_view
from core.views.import_data import import_test_data, download_csv_template
from core.views.modules import sales_dashboard
from core.views.finance import (
    finance_dashboard,
    expense_list,
    expense_create,
    expense_detail,
    expense_settle,
    expense_bulk_settle,
    reconciliation_view,
    invoice_list,
    invoice_create,
    invoice_detail,
)
from core.views.orders import order_detail, order_list, order_bulk_action
from core.views.print_batch import confirm_batch, pick_list, print_pack_file, suggest_batch
from core.views.receive import receive_dashboard_view, receive_line_view, receive_job_all_good_view
from core.views.skus import printed_sku_template, restore_deleted_item, sku_manager
from core.views.vendors import vendor_list

urlpatterns = [
    path("", RedirectView.as_view(url="ops/inventory/orders/", permanent=False), name="root"),
    path("admin/", admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),

    # Inventory (canonical URLs)
    path("ops/inventory/orders/", order_list, name="order-list"),
    path("ops/inventory/orders/bulk-action/", order_bulk_action, name="order-bulk-action"),
    path("ops/inventory/orders/<uuid:order_id>/", order_detail, name="order-detail"),
    path("ops/inventory/print-batches/", suggest_batch, name="print-batch-suggest"),
    path("ops/inventory/print-batches/confirm/", confirm_batch, name="print-batch-confirm"),
    path("ops/inventory/print-batches/list/", suggest_batch, name="print-batch-list"),
    path("ops/inventory/print-batches/generate/", suggest_batch, name="print-batch-generate"),
    path("ops/inventory/print-batches/pick-list/<uuid:job_id>/", pick_list, name="pick-list"),
    path("ops/inventory/print-packs/<str:filename>/", print_pack_file, name="print-pack-file"),
    path("media/print_packs/<str:filename>", print_pack_file, name="print-pack-file-legacy"),
    path("ops/inventory/receive/", receive_dashboard_view, name="receive-dashboard"),
    path("ops/inventory/receive/<uuid:line_id>/", receive_line_view, name="receive-line"),
    path("ops/inventory/receive-job-all-good/<uuid:job_id>/", receive_job_all_good_view, name="receive-job-all-good"),
    path("ops/inventory/adjust/", adjust_inventory, name="adjust-inventory"),
    path("ops/inventory/forecast/", forecast_view, name="forecast"),
    path("ops/inventory/skus/", sku_manager, name="sku-manager"),
    path("ops/inventory/skus/template/", printed_sku_template, name="printed-sku-template"),
    path("ops/inventory/skus/restore/<uuid:item_id>/", restore_deleted_item, name="restore-deleted-item"),
    path("ops/inventory/vendors/", vendor_list, name="vendor-list"),
    path("ops/inventory/audit-log/", audit_log, name="audit-log"),
    path("ops/inventory/webhook-events/", webhook_event_log, name="webhook-event-log"),
    path("ops/inventory/import/", import_test_data, name="import-test-data"),
    path("ops/inventory/import/template/<str:template_name>/", download_csv_template, name="download-csv-template"),

    # Legacy inventory aliases kept to avoid breaking existing links/bookmarks
    path("ops/orders/", RedirectView.as_view(pattern_name="order-list", permanent=False), name="order-list-legacy"),
    path("ops/orders/<uuid:order_id>/", order_detail, name="order-detail-legacy"),
    path("ops/print-batches/", RedirectView.as_view(pattern_name="print-batch-suggest", permanent=False), name="print-batch-suggest-legacy"),
    path("ops/print-batches/confirm/", confirm_batch, name="print-batch-confirm-legacy"),
    path("ops/print-batches/list/", RedirectView.as_view(pattern_name="print-batch-list", permanent=False), name="print-batch-list-legacy"),
    path("ops/print-batches/generate/", RedirectView.as_view(pattern_name="print-batch-generate", permanent=False), name="print-batch-generate-legacy"),
    path("ops/print-batches/pick-list/<uuid:job_id>/", pick_list, name="pick-list-legacy"),
    path("ops/receive/", RedirectView.as_view(pattern_name="receive-dashboard", permanent=False), name="receive-dashboard-legacy"),
    path("ops/receive/<uuid:line_id>/", receive_line_view, name="receive-line-legacy"),
    path("ops/receive-job-all-good/<uuid:job_id>/", receive_job_all_good_view, name="receive-job-all-good-legacy"),
    path("ops/forecast/", RedirectView.as_view(pattern_name="forecast", permanent=False), name="forecast-legacy"),
    path("ops/audit-log/", RedirectView.as_view(pattern_name="audit-log", permanent=False), name="audit-log-legacy"),

    # Non-inventory modules
    path("ops/sales/", sales_dashboard, name="sales-dashboard"),
    path("ops/finance/", finance_dashboard, name="finance-dashboard"),


    # Finance Management
    path("ops/finance/expenses/", expense_list, name="expense-list"),
    path("ops/finance/expenses/new/", expense_create, name="expense-create"),
    path("ops/finance/expenses/<uuid:expense_id>/", expense_detail, name="expense-detail"),
    path("ops/finance/expenses/<uuid:expense_id>/settle/", expense_settle, name="expense-settle"),
    path("ops/finance/expenses/bulk/settle/", expense_bulk_settle, name="expense-bulk-settle"),
    path("ops/finance/reconciliation/", reconciliation_view, name="reconciliation"),
    path("ops/finance/invoices/", invoice_list, name="invoice-list"),
    path("ops/finance/invoices/new/", invoice_create, name="invoice-create"),
    path("ops/finance/invoices/<uuid:invoice_id>/", invoice_detail, name="invoice-detail"),

        # Webhooks
    path("webhooks/shopify/", shopify_webhook_view, name="shopify-webhook"),
]

# Serve user-uploaded media (print pack PDFs) during local development.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

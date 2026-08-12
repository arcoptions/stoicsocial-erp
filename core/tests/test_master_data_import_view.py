from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from core.models import BlankSKU, Design, PrintedSKU


class MasterDataImportViewTests(TestCase):
    def setUp(self) -> None:
        user_model = get_user_model()
        self.superuser = user_model.objects.create_superuser(
            username="master-admin",
            email="admin@example.com",
            password="test-password",
        )
        self.regular_user = user_model.objects.create_user(
            username="operator",
            password="test-password",
        )
        self.url = reverse("import-master-data")

    @staticmethod
    def _csv_file(name: str, content: str) -> SimpleUploadedFile:
        return SimpleUploadedFile(name, content.encode("utf-8"), content_type="text/csv")

    def _bundle(self) -> dict[str, SimpleUploadedFile]:
        return {
            "designs": self._csv_file(
                "designs.csv",
                "design_name,colour,blank_fabric\nProduction Design,Black,180 GSM\n",
            ),
            "blank_skus": self._csv_file(
                "blank_skus.csv",
                "fabric,colour,size,on_hand\n180 GSM,Black,M,25\n",
            ),
            "printed_skus": self._csv_file(
                "printed_skus.csv",
                "design_name,colour,size,on_hand,blank_fabric\nProduction Design,Black,M,4,180 GSM\n",
            ),
        }

    def test_regular_user_is_forbidden(self) -> None:
        self.client.force_login(self.regular_user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)

    def test_superuser_can_open_page_and_download_templates(self) -> None:
        self.client.force_login(self.superuser)

        page_response = self.client.get(self.url)
        download_response = self.client.get(reverse("download-master-data-templates"))

        self.assertEqual(page_response.status_code, 200)
        self.assertContains(page_response, "Master Data Import")
        self.assertEqual(download_response.status_code, 200)
        self.assertEqual(
            download_response["Content-Disposition"],
            'attachment; filename="BoldERP_New_Data_Templates.zip"',
        )

    def test_dry_run_does_not_write_data_or_require_confirmation(self) -> None:
        self.client.force_login(self.superuser)

        response = self.client.post(self.url, {**self._bundle(), "dry_run": "on"}, follow=True)

        self.assertContains(response, "Master data validated successfully.")
        self.assertFalse(Design.objects.exists())
        self.assertFalse(BlankSKU.objects.exists())
        self.assertFalse(PrintedSKU.objects.exists())

    def test_real_import_requires_confirmation(self) -> None:
        self.client.force_login(self.superuser)

        response = self.client.post(self.url, self._bundle(), follow=True)

        self.assertContains(response, "Confirm that this import may update existing master data")
        self.assertFalse(Design.objects.exists())

    def test_superuser_can_import_master_data(self) -> None:
        self.client.force_login(self.superuser)

        response = self.client.post(
            self.url,
            {**self._bundle(), "confirm_import": "on"},
            follow=True,
        )

        self.assertContains(response, "Master data imported successfully.")
        blank_sku = BlankSKU.objects.get(fabric="180 GSM", colour="Black", size="M")
        printed_sku = PrintedSKU.objects.get(
            design__name="Production Design",
            colour="Black",
            size="M",
        )
        self.assertEqual(blank_sku.on_hand, 25)
        self.assertEqual(printed_sku.on_hand, 4)
        self.assertEqual(printed_sku.blank_sku, blank_sku)
        self.assertFalse(printed_sku.is_test_data)
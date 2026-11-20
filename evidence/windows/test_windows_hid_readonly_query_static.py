#!/usr/bin/env python3
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "windows_hid_readonly_query.ps1"
STATUS = ROOT / "docs" / "custom-flow-status.md"


class WindowsHidQueryStaticAuditTests(unittest.TestCase):
    def setUp(self):
        self.text = SCRIPT.read_text(encoding="utf-8")
        self.lowered = self.text.lower()

    def test_uses_only_readonly_windows_api_surface(self):
        forbidden = (
            "writefile",
            "deviceiocontrol",
            "hidd_set",
            "setupdiset",
            "regsetvalue",
            "netsh",
            "new-service",
            "set-service",
            "start-process",
            "runasadministrator",
            "hidd_getmanufacturerstring",
            "hidd_getproductstring",
            "hidd_getserialnumberstring",
        )
        self.assertEqual([], [name for name in forbidden if name in self.lowered])

    def test_uses_exact_spelling_and_required_apis(self):
        required = (
            "SetupDiGetClassDevs",
            "SetupDiEnumDeviceInterfaces",
            "SetupDiGetDeviceInterfaceDetail",
            "SetupDiGetDeviceInstanceId",
            "HidD_GetPreparsedData",
            "HidP_GetCaps",
            "HidD_FreePreparsedData",
            "HidD_GetAttributes",
            "CreateFileW",
        )
        self.assertTrue(all(name in self.text for name in required))
        self.assertEqual(self.text.count("[DllImport("), self.text.count("ExactSpelling = true"))
        self.assertIn(
            'EntryPoint = "SetupDiGetDeviceInstanceIdW", ExactSpelling = true, SetLastError = true, CharSet = CharSet.Unicode',
            self.text,
        )

    def test_hidp_caps_has_complete_sixty_four_byte_native_layout(self):
        match = re.search(r"public struct HIDP_CAPS\s*\{(.*?)\n    \}", self.text, re.S)
        self.assertIsNotNone(match)
        layout = match.group(1)
        initial_fields = [
            "Usage",
            "UsagePage",
            "InputReportByteLength",
            "OutputReportByteLength",
            "FeatureReportByteLength",
        ]
        trailing_fields = [
            "NumberLinkCollectionNodes",
            "NumberInputButtonCaps",
            "NumberInputValueCaps",
            "NumberInputDataIndices",
            "NumberOutputButtonCaps",
            "NumberOutputValueCaps",
            "NumberOutputDataIndices",
            "NumberFeatureButtonCaps",
            "NumberFeatureValueCaps",
            "NumberFeatureDataIndices",
        ]
        self.assertTrue(all(f"public ushort {name};" in layout for name in initial_fields))
        self.assertIn("SizeConst = 17", layout)
        self.assertTrue(all(f"public ushort {name};" in layout for name in trailing_fields))
        self.assertIn("HIDP_CAPS_REQUIRED_SIZE = 64", self.text)
        self.assertIn('"Reserved") != (IntPtr)10', self.text)
        self.assertIn('"NumberLinkCollectionNodes") != (IntPtr)44', self.text)
        self.assertIn('"NumberFeatureDataIndices") != (IntPtr)62', self.text)

    def test_hidp_caps_success_is_windows_hidp_status(self):
        self.assertIn("HIDP_STATUS_SUCCESS = 0x00110000", self.text)
        self.assertIn("item.CapsStatus == HIDP_STATUS_SUCCESS", self.text)
        self.assertNotIn("item.CapsStatus == 0", self.text)

    def test_createfile_uses_metadata_access_sharing_and_open_existing(self):
        self.assertIn("DESIRED_ACCESS_METADATA_ONLY = 0", self.text)
        self.assertIn("FILE_SHARE_READ = 0x00000001", self.text)
        self.assertIn("FILE_SHARE_WRITE = 0x00000002", self.text)
        self.assertIn("OPEN_EXISTING = 3", self.text)
        self.assertIn("DESIRED_ACCESS_METADATA_ONLY,", self.text)
        self.assertIn("FILE_SHARE_READ | FILE_SHARE_WRITE,", self.text)
        self.assertIn("OPEN_EXISTING,", self.text)
        self.assertNotIn("        1, // OPEN_EXISTING", self.text)

    def test_detail_buffer_is_dynamic_and_csharp5_compatible(self):
        self.assertNotIn("SP_DEVICE_INTERFACE_DETAIL_DATA", self.text)
        self.assertIn("Marshal.AllocHGlobal((int)requiredDetailSize)", self.text)
        self.assertIn("Marshal.WriteInt32(detailBuffer, IntPtr.Size == 8 ? 8 : 6)", self.text)
        self.assertIn("Marshal.PtrToStringUni(IntPtr.Add(detailBuffer, 4))", self.text)
        self.assertIn("uint ignoredDetailSize", self.text)
        self.assertIn("ERROR_NO_MORE_ITEMS = 259", self.text)

    def test_script_avoids_post_csharp5_syntax(self):
        for source in ("out _", "PtrToStructure<", "using var ", "$\""):
            self.assertNotIn(source, self.text)

    def test_ble_candidates_are_not_excluded_before_native_attributes(self):
        self.assertIn('upperPath.Contains("BTHLEDEVICE")', self.text)
        self.assertIn('upperPath.Contains("BLUETOOTHDEVICE")', self.text)
        self.assertNotIn("PathIsTarget(item.DevicePath)", self.text)
        self.assertIn("if (includeAll || IsTarget(item.VendorId, item.ProductId))", self.text)
        self.assertIn("item.AttributesSucceeded = HidD_GetAttributes(handle, ref attributes);", self.text)

    def test_targets_and_hid_collection_fields_are_present(self):
        self.assertIn("VID_36B0&PID_3002", self.text)
        self.assertIn("VID_046D&PID_B01B", self.text)
        for field in (
            "UsagePage",
            "Usage",
            "InputReportByteLength",
            "OutputReportByteLength",
            "FeatureReportByteLength",
            "OpenErrorCode",
        ):
            self.assertIn(field, self.text)

    def test_reports_permission_and_query_gaps(self):
        for field in (
            "OpenSucceeded",
            "OpenErrorCode",
            "AttributesSucceeded",
            "CapsSucceeded",
            "CapsStatus",
            "QueryError",
        ):
            self.assertIn(field, self.text)

    def test_json_output_is_stable_for_empty_and_single_results(self):
        self.assertIn("ConvertTo-Json -InputObject @($results) -Depth 4", self.text)
        self.assertNotIn("$results | ConvertTo-Json", self.text)

    def test_documentation_does_not_default_to_execution_policy_bypass(self):
        status = STATUS.read_text(encoding="utf-8")
        self.assertNotIn("-ExecutionPolicy Bypass -File", status)
        self.assertIn("powershell -NoProfile -File", status)


if __name__ == "__main__":
    unittest.main()

param(
    [switch]$All
)

$ErrorActionPreference = "Stop"

$hidQuerySource = @"
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Win32.SafeHandles;

public static class WindowsHidReadOnlyQuery
{
    private const int HIDP_STATUS_SUCCESS = 0x00110000;
    private const int HIDP_CAPS_REQUIRED_SIZE = 64;
    private const int ERROR_NO_MORE_ITEMS = 259;
    private const uint DESIRED_ACCESS_METADATA_ONLY = 0;
    private const uint FILE_SHARE_READ = 0x00000001;
    private const uint FILE_SHARE_WRITE = 0x00000002;
    private const uint OPEN_EXISTING = 3;

    [StructLayout(LayoutKind.Sequential)]
    public struct SP_DEVICE_INTERFACE_DATA
    {
        public int cbSize;
        public Guid InterfaceClassGuid;
        public uint Flags;
        public IntPtr Reserved;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct SP_DEVINFO_DATA
    {
        public int cbSize;
        public Guid ClassGuid;
        public uint DevInst;
        public IntPtr Reserved;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct HIDD_ATTRIBUTES
    {
        public uint cbSize;
        public ushort VendorId;
        public ushort ProductId;
        public ushort VersionNumber;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct HIDP_CAPS
    {
        public ushort Usage;
        public ushort UsagePage;
        public ushort InputReportByteLength;
        public ushort OutputReportByteLength;
        public ushort FeatureReportByteLength;
        [MarshalAs(UnmanagedType.ByValArray, SizeConst = 17)]
        public ushort[] Reserved;
        public ushort NumberLinkCollectionNodes;
        public ushort NumberInputButtonCaps;
        public ushort NumberInputValueCaps;
        public ushort NumberInputDataIndices;
        public ushort NumberOutputButtonCaps;
        public ushort NumberOutputValueCaps;
        public ushort NumberOutputDataIndices;
        public ushort NumberFeatureButtonCaps;
        public ushort NumberFeatureValueCaps;
        public ushort NumberFeatureDataIndices;
    }

    [DllImport("setupapi.dll", EntryPoint = "SetupDiGetClassDevsW", ExactSpelling = true, SetLastError = true)]
    private static extern IntPtr SetupDiGetClassDevs(
        ref Guid classGuid,
        IntPtr enumerator,
        IntPtr hwndParent,
        uint flags);

    [DllImport("setupapi.dll", ExactSpelling = true, SetLastError = true)]
    private static extern bool SetupDiEnumDeviceInterfaces(
        IntPtr deviceInfoSet,
        IntPtr deviceInfoData,
        ref Guid interfaceClassGuid,
        uint memberIndex,
        ref SP_DEVICE_INTERFACE_DATA deviceInterfaceData);

    [DllImport("setupapi.dll", EntryPoint = "SetupDiGetDeviceInterfaceDetailW", ExactSpelling = true, SetLastError = true)]
    private static extern bool SetupDiGetDeviceInterfaceDetail(
        IntPtr deviceInfoSet,
        ref SP_DEVICE_INTERFACE_DATA deviceInterfaceData,
        IntPtr deviceInterfaceDetailData,
        uint deviceInterfaceDetailDataSize,
        out uint requiredSize,
        ref SP_DEVINFO_DATA deviceInfoData);

    [DllImport("setupapi.dll", EntryPoint = "SetupDiGetDeviceInstanceIdW", ExactSpelling = true, SetLastError = true, CharSet = CharSet.Unicode)]
    private static extern bool SetupDiGetDeviceInstanceId(
        IntPtr deviceInfoSet,
        ref SP_DEVINFO_DATA deviceInfoData,
        StringBuilder deviceInstanceId,
        uint deviceInstanceIdSize,
        out uint requiredSize);

    [DllImport("setupapi.dll", ExactSpelling = true, SetLastError = true)]
    private static extern bool SetupDiDestroyDeviceInfoList(IntPtr deviceInfoSet);

    [DllImport("kernel32.dll", ExactSpelling = true, SetLastError = true, CharSet = CharSet.Unicode)]
    private static extern SafeFileHandle CreateFileW(
        string fileName,
        uint desiredAccess,
        uint shareMode,
        IntPtr securityAttributes,
        uint creationDisposition,
        uint flagsAndAttributes,
        IntPtr templateFile);

    [DllImport("hid.dll", ExactSpelling = true, SetLastError = true)]
    private static extern bool HidD_GetPreparsedData(
        SafeFileHandle hidDeviceObject,
        out IntPtr preparsedData);

    [DllImport("hid.dll", ExactSpelling = true, SetLastError = true)]
    private static extern bool HidD_FreePreparsedData(IntPtr preparsedData);

    [DllImport("hid.dll", ExactSpelling = true, SetLastError = true)]
    private static extern int HidP_GetCaps(IntPtr preparsedData, ref HIDP_CAPS capabilities);

    [DllImport("hid.dll", ExactSpelling = true, SetLastError = true)]
    private static extern bool HidD_GetAttributes(
        SafeFileHandle hidDeviceObject,
        ref HIDD_ATTRIBUTES attributes);

    public sealed class HidDeviceInfo
    {
        public string DeviceInstanceId;
        public string DevicePath;
        public ushort VendorId;
        public ushort ProductId;
        public ushort VersionNumber;
        public ushort Usage;
        public ushort UsagePage;
        public ushort InputReportByteLength;
        public ushort OutputReportByteLength;
        public ushort FeatureReportByteLength;
        public bool OpenSucceeded;
        public int OpenErrorCode;
        public bool AttributesSucceeded;
        public bool CapsSucceeded;
        public int CapsStatus;
        public string QueryError;
    }

    public static void ValidateHidpCapsLayout()
    {
        int actualSize = Marshal.SizeOf(typeof(HIDP_CAPS));
        if (actualSize != HIDP_CAPS_REQUIRED_SIZE)
        {
            throw new InvalidOperationException(
                "HIDP_CAPS managed layout is " + actualSize +
                " bytes, native layout requires " + HIDP_CAPS_REQUIRED_SIZE);
        }
        if (Marshal.OffsetOf(typeof(HIDP_CAPS), "Reserved") != (IntPtr)10)
        {
            throw new InvalidOperationException("HIDP_CAPS Reserved offset must be 10");
        }
        if (Marshal.OffsetOf(typeof(HIDP_CAPS), "NumberLinkCollectionNodes") != (IntPtr)44)
        {
            throw new InvalidOperationException("HIDP_CAPS NumberLinkCollectionNodes offset must be 44");
        }
        if (Marshal.OffsetOf(typeof(HIDP_CAPS), "NumberFeatureDataIndices") != (IntPtr)62)
        {
            throw new InvalidOperationException("HIDP_CAPS NumberFeatureDataIndices offset must be 62");
        }
    }

    private static bool IsTarget(ushort vendorId, ushort productId)
    {
        return (vendorId == 0x36B0 && productId == 0x3002) ||
               (vendorId == 0x046D && productId == 0xB01B);
    }

    private static bool HasStandardTargetPath(string devicePath)
    {
        if (string.IsNullOrEmpty(devicePath))
        {
            return false;
        }
        string upperPath = devicePath.ToUpperInvariant();
        return upperPath.Contains("VID_36B0&PID_3002") ||
               upperPath.Contains("VID_046D&PID_B01B");
    }

    private static bool MayBeTargetPath(string devicePath)
    {
        if (HasStandardTargetPath(devicePath))
        {
            return true;
        }
        string upperPath = devicePath.ToUpperInvariant();
        return upperPath.Contains("BTHLEDEVICE") || upperPath.Contains("BLUETOOTHDEVICE");
    }

    private static string GetDevicePath(
        IntPtr infoSet,
        ref SP_DEVICE_INTERFACE_DATA interfaceData,
        ref SP_DEVINFO_DATA devInfo)
    {
        uint requiredDetailSize;
        if (SetupDiGetDeviceInterfaceDetail(
                infoSet,
                ref interfaceData,
                IntPtr.Zero,
                0,
                out requiredDetailSize,
                ref devInfo))
        {
            throw new Win32Exception("SetupDiGetDeviceInterfaceDetail unexpectedly succeeded without a buffer");
        }
        if (requiredDetailSize < 6 || requiredDetailSize > int.MaxValue)
        {
            throw new Win32Exception(
                Marshal.GetLastWin32Error(),
                "SetupDiGetDeviceInterfaceDetail returned invalid size " + requiredDetailSize);
        }

        IntPtr detailBuffer = Marshal.AllocHGlobal((int)requiredDetailSize);
        try
        {
            Marshal.WriteInt32(detailBuffer, IntPtr.Size == 8 ? 8 : 6);
            uint ignoredDetailSize;
            if (!SetupDiGetDeviceInterfaceDetail(
                    infoSet,
                    ref interfaceData,
                    detailBuffer,
                    requiredDetailSize,
                    out ignoredDetailSize,
                    ref devInfo))
            {
                throw new Win32Exception(Marshal.GetLastWin32Error());
            }
            return Marshal.PtrToStringUni(IntPtr.Add(detailBuffer, 4));
        }
        finally
        {
            Marshal.FreeHGlobal(detailBuffer);
        }
    }

    public static List<HidDeviceInfo> Enumerate(bool includeAll)
    {
        ValidateHidpCapsLayout();
        var results = new List<HidDeviceInfo>();
        Guid hidGuid = new Guid("4D1E55B2-F16F-11CF-88CB-001111000030");
        IntPtr infoSet = SetupDiGetClassDevs(
            ref hidGuid,
            IntPtr.Zero,
            IntPtr.Zero,
            0x00000012); // DIGCF_PRESENT | DIGCF_DEVICEINTERFACE
        if (infoSet == IntPtr.Zero || infoSet == new IntPtr(-1))
        {
            throw new Win32Exception(Marshal.GetLastWin32Error(), "SetupDiGetClassDevsW failed");
        }

        try
        {
            for (uint index = 0; ; index++)
            {
                var interfaceData = new SP_DEVICE_INTERFACE_DATA();
                interfaceData.cbSize = Marshal.SizeOf(typeof(SP_DEVICE_INTERFACE_DATA));
                if (!SetupDiEnumDeviceInterfaces(
                        infoSet,
                        IntPtr.Zero,
                        ref hidGuid,
                        index,
                        ref interfaceData))
                {
                    int enumError = Marshal.GetLastWin32Error();
                    if (enumError == ERROR_NO_MORE_ITEMS)
                    {
                        break;
                    }
                    throw new Win32Exception(enumError, "SetupDiEnumDeviceInterfaces failed");
                }

                var devInfo = new SP_DEVINFO_DATA();
                devInfo.cbSize = Marshal.SizeOf(typeof(SP_DEVINFO_DATA));
                string devicePath = GetDevicePath(infoSet, ref interfaceData, ref devInfo);
                bool standardTargetPath = HasStandardTargetPath(devicePath);
                if (!includeAll && !standardTargetPath && !MayBeTargetPath(devicePath))
                {
                    continue;
                }

                var instanceId = new StringBuilder(1024);
                uint ignoredInstanceIdSize;
                if (!SetupDiGetDeviceInstanceId(
                        infoSet,
                        ref devInfo,
                        instanceId,
                        (uint)instanceId.Capacity,
                        out ignoredInstanceIdSize))
                {
                    int instanceError = Marshal.GetLastWin32Error();
                    if (includeAll || standardTargetPath)
                    {
                        var instanceGap = new HidDeviceInfo();
                        instanceGap.DevicePath = devicePath;
                        instanceGap.QueryError = "SetupDiGetDeviceInstanceIdW failed: " + instanceError;
                        results.Add(instanceGap);
                    }
                    continue;
                }

                var item = new HidDeviceInfo();
                item.DevicePath = devicePath;
                item.DeviceInstanceId = instanceId.ToString();

                // Metadata-only query: no desired access, shared read/write, OPEN_EXISTING.
                SafeFileHandle handle = CreateFileW(
                    item.DevicePath,
                    DESIRED_ACCESS_METADATA_ONLY,
                    FILE_SHARE_READ | FILE_SHARE_WRITE,
                    IntPtr.Zero,
                    OPEN_EXISTING,
                    0,
                    IntPtr.Zero);
                if (handle == null || handle.IsInvalid)
                {
                    item.OpenErrorCode = Marshal.GetLastWin32Error();
                    if (includeAll || standardTargetPath)
                    {
                        results.Add(item);
                    }
                    continue;
                }

                using (handle)
                {
                    item.OpenSucceeded = true;
                    var attributes = new HIDD_ATTRIBUTES();
                    attributes.cbSize = (uint)Marshal.SizeOf(typeof(HIDD_ATTRIBUTES));
                    item.AttributesSucceeded = HidD_GetAttributes(handle, ref attributes);
                    if (!item.AttributesSucceeded)
                    {
                        item.QueryError = "HidD_GetAttributes failed";
                        if (includeAll || standardTargetPath)
                        {
                            results.Add(item);
                        }
                        continue;
                    }

                    item.VendorId = attributes.VendorId;
                    item.ProductId = attributes.ProductId;
                    item.VersionNumber = attributes.VersionNumber;

                    IntPtr preparsed = IntPtr.Zero;
                    if (!HidD_GetPreparsedData(handle, out preparsed) || preparsed == IntPtr.Zero)
                    {
                        item.QueryError = "HidD_GetPreparsedData failed";
                        if (includeAll || IsTarget(item.VendorId, item.ProductId))
                        {
                            results.Add(item);
                        }
                        continue;
                    }

                    try
                    {
                        var caps = new HIDP_CAPS();
                        caps.Reserved = new ushort[17];
                        item.CapsStatus = HidP_GetCaps(preparsed, ref caps);
                        item.CapsSucceeded = item.CapsStatus == HIDP_STATUS_SUCCESS;
                        if (item.CapsSucceeded)
                        {
                            item.Usage = caps.Usage;
                            item.UsagePage = caps.UsagePage;
                            item.InputReportByteLength = caps.InputReportByteLength;
                            item.OutputReportByteLength = caps.OutputReportByteLength;
                            item.FeatureReportByteLength = caps.FeatureReportByteLength;
                        }
                        else
                        {
                            item.QueryError = "HidP_GetCaps returned " + item.CapsStatus;
                        }
                    }
                    finally
                    {
                        HidD_FreePreparsedData(preparsed);
                    }

                    if (includeAll || IsTarget(item.VendorId, item.ProductId))
                    {
                        results.Add(item);
                    }
                }
            }
        }
        finally
        {
            SetupDiDestroyDeviceInfoList(infoSet);
        }

        return results;
    }
}
"@

Add-Type -TypeDefinition $hidQuerySource -Language CSharp
$results = [WindowsHidReadOnlyQuery]::Enumerate([bool]$All)
ConvertTo-Json -InputObject @($results) -Depth 4

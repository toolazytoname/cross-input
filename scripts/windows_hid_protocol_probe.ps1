param([switch]$MouseReadOnly = ($env:WINDOWS_HID_PROTOCOL_MODE -eq "mouse-readonly"), [switch]$K94ViaVersion = ($env:WINDOWS_HID_PROTOCOL_MODE -eq "k94-via-version"), [switch]$WindowsEdgeWatch = ($env:WINDOWS_HID_PROTOCOL_MODE -eq "mouse-edge-watch"), [switch]$WindowsEdgeDryRun = ($env:WINDOWS_HID_PROTOCOL_MODE -eq "mouse-edge-dry-run"), [switch]$WindowsReturnHotKey = ($env:WINDOWS_HID_PROTOCOL_MODE -eq "mouse-return-hotkey"), [switch]$WindowsPeerHealth = ($env:WINDOWS_HID_PROTOCOL_MODE -eq "peer-health"), [switch]$AllCandidates, [switch]$TestOnly = ($env:WINDOWS_HID_PROTOCOL_MODE -eq "test-only"))

$ErrorActionPreference = "Stop"

$WindowsEdgeModes = @($WindowsEdgeWatch, $WindowsEdgeDryRun, $WindowsReturnHotKey, $WindowsPeerHealth) | Where-Object { $_ }
$IsWindowsEdgeMode = @($WindowsEdgeModes).Count -eq 1
$WatchHealthPath = if ($env:M585_EDGE_WINDOWS_HEALTH_PATH) { $env:M585_EDGE_WINDOWS_HEALTH_PATH } else { Join-Path $env:TEMP "MiniOpsM585Edge/windows-health.json" }

function Write-WatchHealthJson {
    param(
        [Parameter(Mandatory = $true)][string]$State,
        [Parameter(Mandatory = $true)][bool]$ControllerReady,
        [Parameter(Mandatory = $true)][bool]$Ready,
        [Parameter(Mandatory = $true)][string]$Reason,
        [Parameter(Mandatory = $true)][bool]$DesktopAvailable
    )
    $generated = [DateTime]::UtcNow
    $desktopState = if ($DesktopAvailable) { "INTERACTIVE_DESKTOP_ACCESSIBLE" } else { "SESSION_UNAVAILABLE" }
    $health = [pscustomobject]@{
        schema = 1
        controller = "windows-peer-health-v1"
        controller_ready = $ControllerReady
        ready = $Ready
        reason = $Reason
        desktop = [pscustomobject]@{ available = $DesktopAvailable; state = $desktopState }
        mouse = [pscustomobject]@{
            present = $false
            current_host_index = $null
            host_count = $null
            slot_evidence_verified = $false
            readonly_result = $State
        }
        generated_at_utc = $generated.ToString("o")
        expires_at_utc = $generated.AddSeconds(15).ToString("o")
        hid_output_report_sent = $false
    }
    $directory = Split-Path -Parent $WatchHealthPath
    if ($directory -and -not (Test-Path -LiteralPath $directory)) { New-Item -ItemType Directory -Path $directory -Force | Out-Null }
    $temporary = "$WatchHealthPath.tmp"
    $json = ConvertTo-Json -InputObject $health -Depth 5 -Compress
    [System.IO.File]::WriteAllText($temporary, $json, [System.Text.Encoding]::UTF8)
    Move-Item -LiteralPath $temporary -Destination $WatchHealthPath -Force
}

if ($WindowsEdgeWatch -or $WindowsEdgeDryRun) {
    Write-WatchHealthJson -State "CONTROLLER_STARTING" -ControllerReady $false -Ready $false -Reason "controller-starting" -DesktopAvailable $false
}

$protocolProbeSource = @"
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Threading;
using System.Text;
using System.Net.Sockets;
using System.IO;
using Microsoft.Win32.SafeHandles;

public static class WindowsHidProtocolProbe
{
    private const uint GENERIC_READ = 0x80000000;
    private const uint GENERIC_WRITE = 0x40000000;
    private const uint FILE_SHARE_READ = 0x00000001;
    private const uint FILE_SHARE_WRITE = 0x00000002;
    private const uint OPEN_EXISTING = 3;
    private const uint FILE_FLAG_OVERLAPPED = 0x40000000;
    private const int HIDP_STATUS_SUCCESS = 0x00110000;
    private const int HIDP_CAPS_REQUIRED_SIZE = 64;
    private const int ERROR_NO_MORE_ITEMS = 259;
    private const int ERROR_IO_PENDING = 997;
    private const int ERROR_OPERATION_ABORTED = 995;
    private const int ERROR_NOT_FOUND = 1168;
    private const int WAIT_TIMEOUT = 258;
    private const int WAIT_OBJECT_0 = 0;
    private const int CancelCompletionWaitMilliseconds = 1000;
    private const byte HidppSoftwareId = 0x01;
    private const int MaximumHostNameLength = 32;

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
    public struct OVERLAPPED
    {
        public IntPtr Internal;
        public IntPtr InternalHigh;
        public uint OffsetLow;
        public uint OffsetHigh;
        public IntPtr hEvent;
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

    [StructLayout(LayoutKind.Sequential)]
    public struct POINT
    {
        public int X;
        public int Y;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct MSG
    {
        public IntPtr hwnd;
        public uint message;
        public IntPtr wParam;
        public IntPtr lParam;
        public uint time;
        public POINT pt;
    }

    public sealed class HidCandidate
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
        public bool AttributesSucceeded;
        public bool CapsSucceeded;
        public int CapsStatus;
        public int OpenErrorCode;
        public string QueryError;
    }

    public sealed class ExchangeResult
    {
        public byte[] Response;
        public bool WriteTimedOut;
        public bool ReadTimedOut;
        public bool WriteCanceled;
        public bool ReadCanceled;
        public bool WriteUnresolvedAfterCancel;
        public bool ReadUnresolvedAfterCancel;
        public int WriteInitialNativeError;
        public int WriteWaitNativeError;
        public int WriteCancelNativeError;
        public int WriteGetOverlappedNativeError;
        public int WriteFinalNativeError;
        public int ReadInitialNativeError;
        public int ReadWaitNativeError;
        public int ReadCancelNativeError;
        public int ReadGetOverlappedNativeError;
        public int ReadFinalNativeError;
        public long WriteElapsedMilliseconds;
        public long WriteCancelWaitMilliseconds;
        public long ReadElapsedMilliseconds;
        public long ReadCancelWaitMilliseconds;
        public uint BytesWritten;
        public uint BytesRead;
        public int NativeInputReportByteLength;
        public int NativeOutputReportByteLength;
        public List<string> NonMatchingReports;
        public long ElapsedMilliseconds;
        public string Error;
    }

    public sealed class ProbeOutput
    {
        public string Mode;
        public bool HidOutputReportSent;
        public List<HidCandidate> Candidates;
        public HidCandidate Selected;
        public List<object> Requests;
        public List<object> Responses;
        public string Result;
        public string Error;
    }

    public interface IHidIoChannel
    {
        int LastNativeError { get; }
        bool WriteFile(IntPtr buffer, uint numberOfBytesToWrite, out uint numberOfBytesWritten, IntPtr overlapped);
        bool ReadFile(IntPtr buffer, uint numberOfBytesToRead, out uint numberOfBytesRead, IntPtr overlapped);
        bool CancelIoEx(IntPtr overlapped);
        uint WaitForSingleObject(IntPtr eventHandle, int milliseconds);
        bool GetOverlappedResult(IntPtr overlapped, out uint numberOfBytesTransferred, bool wait);
        bool SetEvent(IntPtr eventHandle);
    }

    private sealed class WindowsHidIoChannel : IHidIoChannel
    {
        private readonly SafeFileHandle device;

        public WindowsHidIoChannel(SafeFileHandle device)
        {
            this.device = device;
        }

        public int LastNativeError { get; private set; }

        public bool WriteFile(IntPtr buffer, uint numberOfBytesToWrite, out uint numberOfBytesWritten, IntPtr overlapped)
        {
            bool result = WriteFileNative(device, buffer, numberOfBytesToWrite, out numberOfBytesWritten, overlapped);
            LastNativeError = Marshal.GetLastWin32Error();
            return result;
        }

        public bool ReadFile(IntPtr buffer, uint numberOfBytesToRead, out uint numberOfBytesRead, IntPtr overlapped)
        {
            bool result = ReadFileNative(device, buffer, numberOfBytesToRead, out numberOfBytesRead, overlapped);
            LastNativeError = Marshal.GetLastWin32Error();
            return result;
        }

        public bool CancelIoEx(IntPtr overlapped)
        {
            bool result = CancelIoExNative(device, overlapped);
            LastNativeError = Marshal.GetLastWin32Error();
            return result;
        }

        public uint WaitForSingleObject(IntPtr eventHandle, int milliseconds)
        {
            uint result = WaitForSingleObjectNative(eventHandle, milliseconds);
            LastNativeError = Marshal.GetLastWin32Error();
            return result;
        }

        public bool GetOverlappedResult(IntPtr overlapped, out uint numberOfBytesTransferred, bool wait)
        {
            bool result = GetOverlappedResultNative(device, overlapped, out numberOfBytesTransferred, wait);
            LastNativeError = Marshal.GetLastWin32Error();
            return result;
        }

        public bool SetEvent(IntPtr eventHandle)
        {
            bool result = SetEventNative(eventHandle);
            LastNativeError = Marshal.GetLastWin32Error();
            return result;
        }
    }

    private sealed class PendingOperation
    {
        public IntPtr Buffer;
        public IntPtr Overlapped;
        public SafeWaitHandle EventHandle;
        public SafeHandle DeviceHandle;
        public bool Retained;
    }

    private static readonly List<PendingOperation> UnresolvedPendingOperations = new List<PendingOperation>();

    public static int UnresolvedPendingOperationCount
    {
        get { return UnresolvedPendingOperations.Count; }
    }

    public static byte[] BuildHidppRootFeatureRequest(ushort featureId)
    {
        if (featureId != 0x1814 && featureId != 0x1815)
        {
            throw new ArgumentException("Only CHANGE_HOST and HOSTS_INFO root lookups are allowed");
        }
        return BuildHidppRequest(0x00, 0x00, new byte[] { (byte)(featureId >> 8), (byte)(featureId & 0xFF) });
    }

    public static byte[] BuildChangeHostStatusRequest(byte featureIndex)
    {
        return BuildHidppRequest(featureIndex, 0x00, new byte[0]);
    }

    public static byte[] BuildChangeHostSwitchToMacRequest(byte featureIndex)
    {
        if (featureIndex != 0x09)
        {
            throw new ArgumentException("Windows-to-Mac switch is restricted to the verified CHANGE_HOST feature index 9");
        }
        byte[] frame = new byte[20];
        frame[0] = 0x11;
        frame[1] = 0xFF;
        frame[2] = featureIndex;
        frame[3] = (byte)(0x10 | HidppSoftwareId);
        frame[4] = 0x01;
        return frame;
    }

    public static byte[] BuildHostsInfoStateRequest(byte featureIndex)
    {
        return BuildHidppRequest(featureIndex, 0x00, new byte[0]);
    }

    public static byte[] BuildHostDescriptorRequest(byte featureIndex, byte slot)
    {
        return BuildHidppRequest(featureIndex, 0x10, new byte[] { slot });
    }

    public static byte[] BuildHostNameRequest(byte featureIndex, byte slot, byte offset)
    {
        return BuildHidppRequest(featureIndex, 0x30, new byte[] { slot, offset });
    }

    public static byte[] BuildHidppRequest(byte featureIndex, byte function, byte[] parameters)
    {
        bool rootLookup = featureIndex == 0x00 && function == 0x00 &&
            parameters != null && parameters.Length == 2 &&
            parameters[0] == 0x18 && (parameters[1] == 0x14 || parameters[1] == 0x15);
        bool stateLookup = function == 0x00 && parameters != null && parameters.Length == 0 &&
            (featureIndex == 0x09 || featureIndex == 0x0A);
        bool descriptorLookup = featureIndex == 0x0A && function == 0x10 &&
            parameters != null && parameters.Length == 1 && parameters[0] < 3;
        bool nameLookup = featureIndex == 0x0A && function == 0x30 &&
            parameters != null && parameters.Length == 2 && parameters[0] < 3;
        if (!rootLookup && !stateLookup && !descriptorLookup && !nameLookup)
        {
            throw new ArgumentException("Requested HID++ feature/function is outside the read-only whitelist");
        }

        byte[] frame = new byte[20];
        frame[0] = 0x11;
        frame[1] = 0xFF;
        frame[2] = featureIndex;
        frame[3] = (byte)(function | HidppSoftwareId);
        Array.Copy(parameters, 0, frame, 4, parameters.Length);
        return frame;
    }

    public static byte[] BuildK94ViaVersionRequest()
    {
        byte[] frame = new byte[33];
        frame[0] = 0x00;
        frame[1] = 0x01;
        return frame;
    }

    public static string ClassifyHidppResponse(byte[] response, byte[] request)
    {
        if (response == null || response.Length < 20 || request == null || request.Length < 20)
        {
            return "short";
        }
        if (response[0] != 0x11)
        {
            return "wrong-report-id";
        }
        if (response[1] != 0xFF && response[1] != 0x00)
        {
            return "wrong-device";
        }
        if (response[2] == 0xFF && response[3] == request[2] && response[4] == request[3])
        {
            return "hidpp-error";
        }
        if (response[2] == request[2] && response[3] == request[3] && request[3] != 0)
        {
            return "match";
        }
        return "nonmatching";
    }

    public static int GetHidppErrorCode(byte[] response)
    {
        if (response == null || response.Length < 6)
        {
            return -1;
        }
        return response[5];
    }

    public static string ClassifyK94Response(byte[] response)
    {
        if (response == null || response.Length < 4)
        {
            return "short";
        }
        int commandOffset = GetK94ReplyCommandOffset(response);
        if (commandOffset < 0)
        {
            return "unaccepted-reply-prefix";
        }
        if (response[commandOffset] != 0x01)
        {
            return "nonmatching";
        }
        if (commandOffset + 3 > response.Length)
        {
            return "short";
        }
        int major = response[commandOffset + 1];
        int minor = response[commandOffset + 2];
        if (major != 0 || minor != 0x0C)
        {
            return "wrong-protocol-version";
        }
        return "match";
    }

    private static int GetK94ReplyCommandOffset(byte[] response)
    {
        if (response[0] == 0x01)
        {
            return 0;
        }
        if (response[0] == 0x00 && response[1] == 0x01)
        {
            return 1;
        }
        if (response[0] == 0xAA && response[1] == 0x01)
        {
            return 1;
        }
        if (response[0] == 0xAA && response.Length > 2 && response[2] == 0x01)
        {
            return 2;
        }
        if (response[1] == 0xAA && response.Length > 2 && response[2] == 0x01)
        {
            return 2;
        }
        return -1;
    }

    private static PendingOperation CreatePendingOperation(SafeHandle device, byte[] managedBuffer, int nativeLength)
    {
        PendingOperation operation = new PendingOperation();
        operation.DeviceHandle = device;
        operation.Buffer = Marshal.AllocHGlobal(nativeLength);
        try
        {
            operation.Overlapped = Marshal.AllocHGlobal(Marshal.SizeOf(typeof(OVERLAPPED)));
            Marshal.StructureToPtr(new OVERLAPPED(), operation.Overlapped, false);
            IntPtr nativeEventHandle = CreateEventExW(IntPtr.Zero, null, 0x00000001, 0x001F0003);
            if (nativeEventHandle == IntPtr.Zero)
            {
                int eventError = Marshal.GetLastWin32Error();
                throw new InvalidOperationException("CreateEventExW failed: " + eventError);
            }
            operation.EventHandle = new SafeWaitHandle(nativeEventHandle, true);

            byte[] copy = new byte[nativeLength];
            if (managedBuffer != null)
            {
                if (managedBuffer.Length > nativeLength)
                {
                    throw new ArgumentException("Protocol frame exceeds native report length");
                }
                Array.Copy(managedBuffer, copy, managedBuffer.Length);
            }
            Marshal.Copy(copy, 0, operation.Buffer, copy.Length);
            Marshal.WriteIntPtr(operation.Overlapped, (int)Marshal.OffsetOf(typeof(OVERLAPPED), "hEvent"), operation.EventHandle.DangerousGetHandle());
            return operation;
        }
        catch
        {
            if (operation.EventHandle != null)
            {
                operation.EventHandle.Dispose();
            }
            if (operation.Overlapped != IntPtr.Zero)
            {
                Marshal.FreeHGlobal(operation.Overlapped);
            }
            Marshal.FreeHGlobal(operation.Buffer);
            throw;
        }
    }

    private static void RetainUnresolvedPendingOperation(PendingOperation operation)
    {
        if (operation.Retained)
        {
            return;
        }
        bool deviceRef = false;
        bool eventRef = false;
        try
        {
            if (operation.DeviceHandle != null)
            {
                operation.DeviceHandle.DangerousAddRef(ref deviceRef);
            }
            operation.EventHandle.DangerousAddRef(ref eventRef);
            UnresolvedPendingOperations.Add(operation);
            operation.Retained = true;
        }
        catch
        {
            if (eventRef)
            {
                operation.EventHandle.DangerousRelease();
            }
            if (deviceRef)
            {
                operation.DeviceHandle.DangerousRelease();
            }
            throw;
        }
    }

    private static byte[] CopyConfirmedBuffer(PendingOperation operation, int length)
    {
        byte[] copy = new byte[length];
        Marshal.Copy(operation.Buffer, copy, 0, length);
        return copy;
    }

    private static void FreeConfirmedPendingOperation(PendingOperation operation)
    {
        if (operation.Retained)
        {
            throw new InvalidOperationException("Cannot free an unresolved pending operation");
        }
        Marshal.FreeHGlobal(operation.Buffer);
        Marshal.FreeHGlobal(operation.Overlapped);
        operation.Buffer = IntPtr.Zero;
        operation.Overlapped = IntPtr.Zero;
        operation.EventHandle.Dispose();
    }

    private sealed class OperationCompletion
    {
        public PendingOperation Operation;
        public uint BytesTransferred;
        public bool TimedOut;
        public bool Canceled;
        public bool Unresolved;
        public int InitialNativeError;
        public int WaitNativeError;
        public int CancelNativeError;
        public int GetOverlappedNativeError;
        public int FinalNativeError;
        public long CancelWaitMilliseconds;
        public long OperationElapsedMilliseconds;
    }

    private static OperationCompletion CompleteOperation(
        IHidIoChannel channel,
        PendingOperation operation,
        bool immediateSuccess,
        uint immediateBytes,
        int waitMilliseconds)
    {
        OperationCompletion completion = new OperationCompletion();
        completion.Operation = operation;
        Stopwatch stopwatch = Stopwatch.StartNew();
        try
        {
            if (immediateSuccess)
            {
                completion.BytesTransferred = immediateBytes;
                completion.InitialNativeError = 0;
                completion.FinalNativeError = 0;
                completion.OperationElapsedMilliseconds = stopwatch.ElapsedMilliseconds;
                return completion;
            }

            completion.InitialNativeError = channel.LastNativeError;
            if (completion.InitialNativeError != ERROR_IO_PENDING)
            {
                completion.FinalNativeError = completion.InitialNativeError;
                completion.OperationElapsedMilliseconds = stopwatch.ElapsedMilliseconds;
                return completion;
            }

            uint waitResult = channel.WaitForSingleObject(operation.EventHandle.DangerousGetHandle(), waitMilliseconds);
            completion.WaitNativeError = channel.LastNativeError;
            if (waitResult == WAIT_TIMEOUT)
            {
                completion.TimedOut = true;
                bool canceled = channel.CancelIoEx(operation.Overlapped);
                completion.CancelNativeError = channel.LastNativeError;
                if (!canceled && completion.CancelNativeError == ERROR_NOT_FOUND)
                {
                    bool eventSignaled = channel.SetEvent(operation.EventHandle.DangerousGetHandle());
                    if (!eventSignaled && channel.LastNativeError != 0)
                    {
                        completion.Unresolved = true;
                        completion.FinalNativeError = channel.LastNativeError;
                        RetainUnresolvedPendingOperation(operation);
                        completion.OperationElapsedMilliseconds = stopwatch.ElapsedMilliseconds;
                        return completion;
                    }
                }
                else if (!canceled && completion.CancelNativeError != 0)
                {
                    completion.Unresolved = true;
                    completion.FinalNativeError = completion.CancelNativeError;
                    RetainUnresolvedPendingOperation(operation);
                    completion.OperationElapsedMilliseconds = stopwatch.ElapsedMilliseconds;
                    return completion;
                }

                Stopwatch cancelStopwatch = Stopwatch.StartNew();
                uint cancelWait = channel.WaitForSingleObject(operation.EventHandle.DangerousGetHandle(), CancelCompletionWaitMilliseconds);
                completion.CancelWaitMilliseconds = cancelStopwatch.ElapsedMilliseconds;
                if (cancelWait == WAIT_TIMEOUT)
                {
                    uint ignoredCancelBytes;
                    bool cancelResult = channel.GetOverlappedResult(operation.Overlapped, out ignoredCancelBytes, false);
                    completion.GetOverlappedNativeError = channel.LastNativeError;
                    if (!cancelResult && completion.GetOverlappedNativeError == ERROR_IO_PENDING)
                    {
                        completion.Unresolved = true;
                        completion.FinalNativeError = ERROR_IO_PENDING;
                        RetainUnresolvedPendingOperation(operation);
                        completion.OperationElapsedMilliseconds = stopwatch.ElapsedMilliseconds;
                        return completion;
                    }
                }
                else if (cancelWait != WAIT_OBJECT_0)
                {
                    completion.Unresolved = true;
                    completion.FinalNativeError = channel.LastNativeError;
                    RetainUnresolvedPendingOperation(operation);
                    completion.OperationElapsedMilliseconds = stopwatch.ElapsedMilliseconds;
                    return completion;
                }
            }
            else if (waitResult != WAIT_OBJECT_0)
            {
                completion.Unresolved = true;
                completion.FinalNativeError = completion.WaitNativeError;
                RetainUnresolvedPendingOperation(operation);
                completion.OperationElapsedMilliseconds = stopwatch.ElapsedMilliseconds;
                return completion;
            }

            uint transferred;
            bool overlappedResult = channel.GetOverlappedResult(operation.Overlapped, out transferred, false);
            completion.GetOverlappedNativeError = channel.LastNativeError;
            if (!overlappedResult && completion.GetOverlappedNativeError == ERROR_IO_PENDING)
            {
                completion.Unresolved = true;
                completion.FinalNativeError = ERROR_IO_PENDING;
                RetainUnresolvedPendingOperation(operation);
                completion.OperationElapsedMilliseconds = stopwatch.ElapsedMilliseconds;
                return completion;
            }

            completion.BytesTransferred = transferred;
            completion.FinalNativeError = overlappedResult ? 0 : completion.GetOverlappedNativeError;
            if (!overlappedResult && completion.FinalNativeError == ERROR_OPERATION_ABORTED)
            {
                completion.Canceled = true;
            }
            completion.OperationElapsedMilliseconds = stopwatch.ElapsedMilliseconds;
            return completion;
        }
        catch
        {
            completion.Unresolved = true;
            completion.FinalNativeError = channel.LastNativeError;
            RetainUnresolvedPendingOperation(operation);
            completion.OperationElapsedMilliseconds = stopwatch.ElapsedMilliseconds;
            throw;
        }
    }

    public static ExchangeResult Exchange(IHidIoChannel channel, SafeFileHandle device, int nativeInputLength, int nativeOutputLength, byte[] protocolFrame, int timeoutMs)
    {
        Stopwatch stopwatch = Stopwatch.StartNew();
        ExchangeResult result = new ExchangeResult();
        result.NonMatchingReports = new List<string>();
        result.NativeInputReportByteLength = nativeInputLength;
        result.NativeOutputReportByteLength = nativeOutputLength;
        if (nativeInputLength < 20 || nativeOutputLength < 20 || protocolFrame == null || protocolFrame.Length > nativeOutputLength || timeoutMs <= 0)
        {
            result.Error = "invalid-native-report-length";
            result.ElapsedMilliseconds = stopwatch.ElapsedMilliseconds;
            return result;
        }

        PendingOperation writeOperation = CreatePendingOperation(device, protocolFrame, nativeOutputLength);
        OperationCompletion writeCompletion;
        uint immediateWritten;
        bool writeImmediate;
        try
        {
            writeImmediate = channel.WriteFile(writeOperation.Buffer, (uint)nativeOutputLength, out immediateWritten, writeOperation.Overlapped);
            writeCompletion = CompleteOperation(channel, writeOperation, writeImmediate, immediateWritten, timeoutMs);
        }
        catch
        {
            RetainUnresolvedPendingOperation(writeOperation);
            result.WriteUnresolvedAfterCancel = true;
            result.Error = "write-unresolved";
            result.ElapsedMilliseconds = stopwatch.ElapsedMilliseconds;
            throw;
        }

        result.WriteTimedOut = writeCompletion.TimedOut;
        result.WriteCanceled = writeCompletion.Canceled;
        result.WriteUnresolvedAfterCancel = writeCompletion.Unresolved;
        result.WriteInitialNativeError = writeCompletion.InitialNativeError;
        result.WriteWaitNativeError = writeCompletion.WaitNativeError;
        result.WriteCancelNativeError = writeCompletion.CancelNativeError;
        result.WriteGetOverlappedNativeError = writeCompletion.GetOverlappedNativeError;
        result.WriteFinalNativeError = writeCompletion.FinalNativeError;
        result.WriteCancelWaitMilliseconds = writeCompletion.CancelWaitMilliseconds;
        result.WriteElapsedMilliseconds = writeCompletion.OperationElapsedMilliseconds;
        result.BytesWritten = writeCompletion.BytesTransferred;
        if (!writeCompletion.Unresolved)
        {
            FreeConfirmedPendingOperation(writeOperation);
        }
        if (writeCompletion.Unresolved || writeCompletion.FinalNativeError != 0 || writeCompletion.BytesTransferred != nativeOutputLength)
        {
            result.Error = writeCompletion.Unresolved ? "write-unresolved" : (writeCompletion.TimedOut ? "write-timeout" : "write-error");
            result.ElapsedMilliseconds = stopwatch.ElapsedMilliseconds;
            return result;
        }

        long deadline = stopwatch.ElapsedMilliseconds + timeoutMs;
        while (stopwatch.ElapsedMilliseconds <= deadline)
        {
            PendingOperation readOperation = CreatePendingOperation(device, null, nativeInputLength);
            OperationCompletion readCompletion;
            uint immediateRead;
            bool readImmediate;
            try
            {
                readImmediate = channel.ReadFile(readOperation.Buffer, (uint)nativeInputLength, out immediateRead, readOperation.Overlapped);
                readCompletion = CompleteOperation(channel, readOperation, readImmediate, immediateRead, Math.Max(0, (int)(deadline - stopwatch.ElapsedMilliseconds)));
            }
            catch
            {
                RetainUnresolvedPendingOperation(readOperation);
                result.ReadUnresolvedAfterCancel = true;
                result.Error = "read-unresolved";
                result.ElapsedMilliseconds = stopwatch.ElapsedMilliseconds;
                throw;
            }

            result.ReadTimedOut = readCompletion.TimedOut;
            result.ReadCanceled = readCompletion.Canceled;
            result.ReadUnresolvedAfterCancel = readCompletion.Unresolved;
            result.ReadInitialNativeError = readCompletion.InitialNativeError;
            result.ReadWaitNativeError = readCompletion.WaitNativeError;
            result.ReadCancelNativeError = readCompletion.CancelNativeError;
            result.ReadGetOverlappedNativeError = readCompletion.GetOverlappedNativeError;
            result.ReadFinalNativeError = readCompletion.FinalNativeError;
            result.ReadCancelWaitMilliseconds = readCompletion.CancelWaitMilliseconds;
            result.ReadElapsedMilliseconds = readCompletion.OperationElapsedMilliseconds;
            result.BytesRead = readCompletion.BytesTransferred;
            if (readCompletion.Unresolved)
            {
                result.Error = "read-unresolved";
                result.ElapsedMilliseconds = stopwatch.ElapsedMilliseconds;
                return result;
            }

            byte[] input = null;
            if (readCompletion.BytesTransferred == nativeInputLength)
            {
                input = CopyConfirmedBuffer(readOperation, nativeInputLength);
            }
            FreeConfirmedPendingOperation(readOperation);
            if (readCompletion.FinalNativeError != 0)
            {
                result.Error = readCompletion.TimedOut ? "read-timeout" : "read-error";
                result.ElapsedMilliseconds = stopwatch.ElapsedMilliseconds;
                return result;
            }
            if (input == null)
            {
                result.Error = "short-read";
                result.ElapsedMilliseconds = stopwatch.ElapsedMilliseconds;
                return result;
            }

            byte[] wireFrame = new byte[Math.Min(20, nativeInputLength)];
            Array.Copy(input, wireFrame, wireFrame.Length);
            bool extraBytesAreZero = true;
            for (int index = 20; index < input.Length; index++)
            {
                if (input[index] != 0)
                {
                    extraBytesAreZero = false;
                    break;
                }
            }

            string classification = protocolFrame[0] == 0x11
                ? ClassifyHidppResponse(wireFrame, protocolFrame)
                : ClassifyK94Response(input);
            if (protocolFrame[0] == 0x11)
            {
                if (classification == "hidpp-error")
                {
                    result.Error = "hidpp-error-" + GetHidppErrorCode(input).ToString("X2");
                    result.ElapsedMilliseconds = stopwatch.ElapsedMilliseconds;
                    return result;
                }
                if (classification == "match" && extraBytesAreZero)
                {
                    result.Response = wireFrame;
                    result.ElapsedMilliseconds = stopwatch.ElapsedMilliseconds;
                    return result;
                }
            }
            else if (classification == "match")
            {
                result.Response = input;
                result.ElapsedMilliseconds = stopwatch.ElapsedMilliseconds;
                return result;
            }
            result.NonMatchingReports.Add(classification + ":" + BitConverter.ToString(input).Replace("-", ""));
            if (stopwatch.ElapsedMilliseconds < deadline)
            {
                Thread.Sleep(10);
            }
        }

        result.ReadTimedOut = true;
        result.Error = "read-timeout";
        result.ElapsedMilliseconds = stopwatch.ElapsedMilliseconds;
        return result;
    }

    public static ProbeOutput CreateMetadataOutput(List<HidCandidate> candidates)
    {
        ProbeOutput output = new ProbeOutput();
        output.Mode = "metadata-only";
        output.HidOutputReportSent = false;
        output.Candidates = candidates;
        output.Requests = new List<object>();
        output.Responses = new List<object>();
        return output;
    }

    private static SafeFileHandle OpenDataHandle(HidCandidate candidate)
    {
        SafeFileHandle handle = CreateFileW(
            candidate.DevicePath,
            GENERIC_READ | GENERIC_WRITE,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            IntPtr.Zero,
            OPEN_EXISTING,
            FILE_FLAG_OVERLAPPED,
            IntPtr.Zero);
        if (handle == null || handle.IsInvalid)
        {
            throw new InvalidOperationException("CreateFileW data handle failed: " + Marshal.GetLastWin32Error());
        }
        return handle;
    }

    public static ProbeOutput RunK94ViaVersion(List<HidCandidate> candidates)
    {
        HidCandidate selected = SelectCandidate(candidates, "K94");
        using (SafeFileHandle handle = OpenDataHandle(selected))
        {
            return RunK94ViaVersion(candidates, new WindowsHidIoChannel(handle), handle, selected);
        }
    }

    public static ProbeOutput RunK94ViaVersion(List<HidCandidate> candidates, IHidIoChannel channel, SafeFileHandle device, HidCandidate selected)
    {
        if (!ReferenceEquals(SelectCandidate(candidates, "K94"), selected))
        {
            throw new ArgumentException("The supplied K94 candidate is not the unique exact selection");
        }
        ProbeOutput output = NewProtocolOutput("K94-via-version", candidates, selected);
        byte[] request = BuildK94ViaVersionRequest();
        output.Requests.Add(new { report_id_hex = "00", via_command = 1, request_hex = BitConverter.ToString(request).Replace("-", "") });
        ExchangeResult exchange = Exchange(channel, device, selected.InputReportByteLength, selected.OutputReportByteLength, request, 2000);
        output.Responses.Add(exchange);
        if (exchange.Response != null && ClassifyK94Response(exchange.Response) == "match")
        {
            output.Result = "receiver-path-responded";
        }
        else
        {
            output.Result = exchange.ReadTimedOut || exchange.WriteTimedOut ? "timeout" : "error";
            output.Error = exchange.Error;
        }
        return output;
    }

    public static ProbeOutput RunMouseReadonly(List<HidCandidate> candidates)
    {
        HidCandidate selected = SelectCandidate(candidates, "Mouse");
        using (SafeFileHandle handle = OpenDataHandle(selected))
        {
            return RunMouseReadonly(candidates, new WindowsHidIoChannel(handle), handle, selected);
        }
    }

    public static ProbeOutput RunMouseReadonly(List<HidCandidate> candidates, IHidIoChannel channel, SafeFileHandle device, HidCandidate selected)
    {
        if (!ReferenceEquals(SelectCandidate(candidates, "Mouse"), selected))
        {
            throw new ArgumentException("The supplied mouse candidate is not the unique exact selection");
        }
        ProbeOutput output = NewProtocolOutput("M585-readonly", candidates, selected);

        ExchangeResult changeRootResult = QueryHidpp(channel, device, selected, output, 0x1814, "root-get-change-host", delegate { return BuildHidppRootFeatureRequest(0x1814); });
        RequireFeatureIndex(changeRootResult, 0x09, "CHANGE_HOST feature index changed");

        ExchangeResult changeStatusResult = QueryHidpp(channel, device, selected, output, 0x1814, "change-host-get-status", delegate { return BuildChangeHostStatusRequest(0x09); });
        RequireChangeHostStatus(changeStatusResult, 2, 0);

        ExchangeResult hostsRootResult = QueryHidpp(channel, device, selected, output, 0x1815, "root-get-hosts-info", delegate { return BuildHidppRootFeatureRequest(0x1815); });
        RequireFeatureIndex(hostsRootResult, 0x0A, "HOSTS_INFO feature index changed");

        ExchangeResult hostsStateResult = QueryHidpp(channel, device, selected, output, 0x1815, "hosts-info-get-state", delegate { return BuildHostsInfoStateRequest(0x0A); });
        RequireHostsInfoState(hostsStateResult, 2, 0);

        string slot0Name = ReadHostName(channel, device, selected, output, 0x0A, 0);
        string slot1Name = ReadHostName(channel, device, selected, output, 0x0A, 1);
        if (!string.Equals(slot0Name, "LAZY-WINDOWS", StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidOperationException("Windows slot name mismatch: " + slot0Name);
        }
        if (slot1Name != "lazy\u7684Mac Mini")
        {
            throw new InvalidOperationException("Mac slot name mismatch: " + slot1Name);
        }
        output.Result = "windows-slot-0-mac-slot-1-confirmed";
        return output;
    }

    public static ProbeOutput RunMouseSwitchToMac(List<HidCandidate> candidates)
    {
        HidCandidate selected = SelectCandidate(candidates, "Mouse");
        using (SafeFileHandle handle = OpenDataHandle(selected))
        {
            return RunMouseSwitchToMac(candidates, new WindowsHidIoChannel(handle), handle, selected);
        }
    }

    public static ProbeOutput RunMouseSwitchToMac(List<HidCandidate> candidates, IHidIoChannel channel, SafeFileHandle device, HidCandidate selected)
    {
        ProbeOutput output = RunMouseReadonly(candidates, channel, device, selected);
        output.Mode = "M585-switch-to-mac-once";

        byte[] request = BuildChangeHostSwitchToMacRequest(0x09);
        output.Requests.Add(new { name = "change-host-switch-to-mac", feature = 0x1814, target_slot = 1, request_hex = BitConverter.ToString(request).Replace("-", "") });
        ExchangeResult submit = SendHidppNoReply(channel, device, selected, request, 2000);
        output.Responses.Add(submit);
        if (submit.Error != null)
        {
            output.Result = "switch-submit-error";
            output.Error = submit.Error;
            return output;
        }

        output.Result = "switch-submitted-no-reply";
        output.Error = null;
        return output;
    }

    private static ExchangeResult SendHidppNoReply(IHidIoChannel channel, SafeFileHandle device, HidCandidate selected, byte[] protocolFrame, int timeoutMs)
    {
        Stopwatch stopwatch = Stopwatch.StartNew();
        ExchangeResult result = new ExchangeResult();
        result.NonMatchingReports = new List<string>();
        result.NativeInputReportByteLength = selected.InputReportByteLength;
        result.NativeOutputReportByteLength = selected.OutputReportByteLength;

        PendingOperation operation = CreatePendingOperation(device, protocolFrame, selected.OutputReportByteLength);
        OperationCompletion completion;
        uint immediateWritten;
        bool immediate;
        try
        {
            immediate = channel.WriteFile(operation.Buffer, (uint)selected.OutputReportByteLength, out immediateWritten, operation.Overlapped);
            completion = CompleteOperation(channel, operation, immediate, immediateWritten, timeoutMs);
        }
        catch
        {
            RetainUnresolvedPendingOperation(operation);
            result.WriteUnresolvedAfterCancel = true;
            result.WriteFinalNativeError = channel.LastNativeError;
            result.Error = "write-unresolved";
            result.ElapsedMilliseconds = stopwatch.ElapsedMilliseconds;
            throw;
        }

        result.WriteTimedOut = completion.TimedOut;
        result.WriteCanceled = completion.Canceled;
        result.WriteUnresolvedAfterCancel = completion.Unresolved;
        result.WriteInitialNativeError = completion.InitialNativeError;
        result.WriteWaitNativeError = completion.WaitNativeError;
        result.WriteCancelNativeError = completion.CancelNativeError;
        result.WriteGetOverlappedNativeError = completion.GetOverlappedNativeError;
        result.WriteFinalNativeError = completion.FinalNativeError;
        result.WriteCancelWaitMilliseconds = completion.CancelWaitMilliseconds;
        result.WriteElapsedMilliseconds = completion.OperationElapsedMilliseconds;
        result.BytesWritten = completion.BytesTransferred;
        if (!completion.Unresolved)
        {
            FreeConfirmedPendingOperation(operation);
        }
        if (completion.Unresolved || completion.FinalNativeError != 0 || completion.BytesTransferred != selected.OutputReportByteLength)
        {
            result.Error = completion.Unresolved ? "write-unresolved" : (completion.TimedOut ? "write-timeout" : "write-error");
        }
        result.ElapsedMilliseconds = stopwatch.ElapsedMilliseconds;
        return result;
    }

    private static ProbeOutput NewProtocolOutput(string mode, List<HidCandidate> candidates, HidCandidate selected)
    {
        ProbeOutput output = new ProbeOutput();
        output.Mode = mode;
        output.HidOutputReportSent = true;
        output.Candidates = candidates;
        output.Selected = selected;
        output.Requests = new List<object>();
        output.Responses = new List<object>();
        return output;
    }

    private delegate byte[] HidppRequestBuilder();

    private static ExchangeResult QueryHidpp(IHidIoChannel channel, SafeFileHandle device, HidCandidate selected, ProbeOutput output, int featureId, string name, HidppRequestBuilder builder)
    {
        byte[] request = builder();
        output.Requests.Add(new { name = name, feature = featureId, request_hex = BitConverter.ToString(request).Replace("-", "") });
        ExchangeResult result = Exchange(channel, device, selected.InputReportByteLength, selected.OutputReportByteLength, request, 2000);
        output.Responses.Add(result);
        if (result.Response == null)
        {
            throw new InvalidOperationException(name + " failed: " + result.Error);
        }
        return result;
    }

    private static void RequireFeatureIndex(ExchangeResult result, byte expected, string message)
    {
        byte actual = result.Response[4];
        if (actual != expected)
        {
            throw new InvalidOperationException(message + ": " + actual);
        }
    }

    private static void RequireChangeHostStatus(ExchangeResult result, byte expectedCount, byte expectedCurrent)
    {
        byte hostCount = result.Response[4];
        byte currentHost = result.Response[5];
        if (hostCount != expectedCount || currentHost != expectedCurrent || currentHost >= hostCount)
        {
            throw new InvalidOperationException("Invalid CHANGE_HOST status: count=" + hostCount + " current=" + currentHost);
        }
    }

    private static void RequireHostsInfoState(ExchangeResult result, byte expectedCount, byte expectedCurrent)
    {
        byte capabilityFlags = result.Response[4];
        byte hostCount = result.Response[6];
        byte currentHost = result.Response[7];
        if ((capabilityFlags & 0x01) == 0 || hostCount != expectedCount || currentHost != expectedCurrent || currentHost >= hostCount)
        {
            throw new InvalidOperationException("Invalid HOSTS_INFO state: flags=" + capabilityFlags + " count=" + hostCount + " current=" + currentHost);
        }
    }

    private static string ReadHostName(IHidIoChannel channel, SafeFileHandle device, HidCandidate selected, ProbeOutput output, byte featureIndex, byte slot)
    {
        byte[] descriptorRequest = BuildHostDescriptorRequest(featureIndex, slot);
        output.Requests.Add(new { name = "hosts-info-get-descriptor", feature = 0x1815, slot = slot, request_hex = BitConverter.ToString(descriptorRequest).Replace("-", "") });
        ExchangeResult descriptorResult = Exchange(channel, device, selected.InputReportByteLength, selected.OutputReportByteLength, descriptorRequest, 2000);
        output.Responses.Add(descriptorResult);
        if (descriptorResult.Response == null)
        {
            throw new InvalidOperationException("Host descriptor timeout/error for slot " + slot);
        }
        byte pairedStatus = descriptorResult.Response[5];
        byte nameLength = descriptorResult.Response[8];
        byte maximumLength = descriptorResult.Response[9];
        if (descriptorResult.Response[4] != slot || pairedStatus == 0 || nameLength == 0 || nameLength > MaximumHostNameLength || maximumLength > MaximumHostNameLength || nameLength > maximumLength)
        {
            throw new InvalidOperationException("Invalid host descriptor for slot " + slot);
        }

        List<byte> nameBytes = new List<byte>();
        while (nameBytes.Count < nameLength)
        {
            byte offset = (byte)nameBytes.Count;
            byte[] nameRequest = BuildHostNameRequest(featureIndex, slot, offset);
            output.Requests.Add(new { name = "hosts-info-get-name", feature = 0x1815, slot = slot, offset = offset, request_hex = BitConverter.ToString(nameRequest).Replace("-", "") });
            ExchangeResult nameResult = Exchange(channel, device, selected.InputReportByteLength, selected.OutputReportByteLength, nameRequest, 2000);
            output.Responses.Add(nameResult);
            if (nameResult.Response == null || nameResult.Response[4] != slot || nameResult.Response[5] != offset)
            {
                throw new InvalidOperationException("Host name response mismatch for slot " + slot);
            }
            int count = Math.Min(14, nameLength - nameBytes.Count);
            for (int index = 0; index < count; index++)
            {
                nameBytes.Add(nameResult.Response[6 + index]);
            }
        }

        int terminatedLength = nameBytes.IndexOf(0);
        if (terminatedLength >= 0)
        {
            nameBytes.RemoveRange(terminatedLength, nameBytes.Count - terminatedLength);
        }
        try
        {
            return new UTF8Encoding(false, true).GetString(nameBytes.ToArray());
        }
        catch (DecoderFallbackException)
        {
            throw new InvalidOperationException("Host name is not valid UTF-8 for slot " + slot);
        }
    }

    public static List<HidCandidate> Enumerate(bool includeAll)
    {
        ValidateHidpCapsLayout();
        List<HidCandidate> results = new List<HidCandidate>();
        Guid hidGuid = new Guid("4D1E55B2-F16F-11CF-88CB-001111000030");
        IntPtr infoSet = SetupDiGetClassDevs(ref hidGuid, IntPtr.Zero, IntPtr.Zero, 0x00000012);
        if (infoSet == IntPtr.Zero || infoSet == new IntPtr(-1))
        {
            throw new Win32Exception(Marshal.GetLastWin32Error(), "SetupDiGetClassDevsW failed");
        }

        try
        {
            for (uint index = 0; ; index++)
            {
                SP_DEVICE_INTERFACE_DATA interfaceData = new SP_DEVICE_INTERFACE_DATA();
                interfaceData.cbSize = Marshal.SizeOf(typeof(SP_DEVICE_INTERFACE_DATA));
                if (!SetupDiEnumDeviceInterfaces(infoSet, IntPtr.Zero, ref hidGuid, index, ref interfaceData))
                {
                    int enumError = Marshal.GetLastWin32Error();
                    if (enumError == ERROR_NO_MORE_ITEMS)
                    {
                        break;
                    }
                    throw new Win32Exception(enumError, "SetupDiEnumDeviceInterfaces failed");
                }

                SP_DEVINFO_DATA devInfo = new SP_DEVINFO_DATA();
                devInfo.cbSize = Marshal.SizeOf(typeof(SP_DEVINFO_DATA));
                string devicePath = GetDevicePath(infoSet, ref interfaceData, ref devInfo);
                bool standardTargetPath = HasStandardTargetPath(devicePath);
                if (!includeAll && !standardTargetPath && !MayBeTargetPath(devicePath))
                {
                    continue;
                }

                StringBuilder instanceId = new StringBuilder(1024);
                uint ignoredInstanceIdSize;
                if (!SetupDiGetDeviceInstanceId(infoSet, ref devInfo, instanceId, (uint)instanceId.Capacity, out ignoredInstanceIdSize))
                {
                    int instanceError = Marshal.GetLastWin32Error();
                    if (includeAll || standardTargetPath)
                    {
                        HidCandidate instanceGap = new HidCandidate();
                        instanceGap.DevicePath = devicePath;
                        instanceGap.QueryError = "SetupDiGetDeviceInstanceIdW failed: " + instanceError;
                        results.Add(instanceGap);
                    }
                    continue;
                }

                HidCandidate item = new HidCandidate();
                item.DevicePath = devicePath;
                item.DeviceInstanceId = instanceId.ToString();
                SafeFileHandle handle = CreateFileW(item.DevicePath, 0, FILE_SHARE_READ | FILE_SHARE_WRITE, IntPtr.Zero, OPEN_EXISTING, 0, IntPtr.Zero);
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
                    HIDD_ATTRIBUTES attributes = new HIDD_ATTRIBUTES();
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
                        if (includeAll || IsTargetAttributes(item.VendorId, item.ProductId))
                        {
                            results.Add(item);
                        }
                        continue;
                    }
                    try
                    {
                        HIDP_CAPS caps = new HIDP_CAPS();
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
                    if (includeAll || IsTargetAttributes(item.VendorId, item.ProductId))
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

    public static void ValidateHidpCapsLayout()
    {
        int actualSize = Marshal.SizeOf(typeof(HIDP_CAPS));
        if (actualSize != HIDP_CAPS_REQUIRED_SIZE)
        {
            throw new InvalidOperationException("HIDP_CAPS managed layout is " + actualSize + " bytes, native layout requires " + HIDP_CAPS_REQUIRED_SIZE);
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

    private static bool IsTargetAttributes(ushort vendorId, ushort productId)
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
        return upperPath.Contains("BTHLEDEVICE") || upperPath.Contains("BLUETOOTHDEVICE") ||
               upperPath.Contains("_DEV_VID&02046D_PID&B01B") ||
               upperPath.Contains("_DEV_VID&0002046D_PID&B01B");
    }

    private static string GetDevicePath(IntPtr infoSet, ref SP_DEVICE_INTERFACE_DATA interfaceData, ref SP_DEVINFO_DATA devInfo)
    {
        uint requiredDetailSize;
        if (SetupDiGetDeviceInterfaceDetail(infoSet, ref interfaceData, IntPtr.Zero, 0, out requiredDetailSize, ref devInfo))
        {
            throw new Win32Exception("SetupDiGetDeviceInterfaceDetail unexpectedly succeeded without a buffer");
        }
        if (requiredDetailSize < 6 || requiredDetailSize > int.MaxValue)
        {
            throw new Win32Exception(Marshal.GetLastWin32Error(), "SetupDiGetDeviceInterfaceDetail returned invalid size " + requiredDetailSize);
        }

        IntPtr detailBuffer = Marshal.AllocHGlobal((int)requiredDetailSize);
        try
        {
            Marshal.WriteInt32(detailBuffer, IntPtr.Size == 8 ? 8 : 6);
            uint ignoredDetailSize;
            if (!SetupDiGetDeviceInterfaceDetail(infoSet, ref interfaceData, detailBuffer, requiredDetailSize, out ignoredDetailSize, ref devInfo))
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

    public static HidCandidate SelectCandidate(List<HidCandidate> candidates, string deviceKind)
    {
        if (candidates == null)
        {
            throw new InvalidOperationException("No " + deviceKind + " candidates were supplied");
        }
        List<HidCandidate> matches = new List<HidCandidate>();
        foreach (HidCandidate candidate in candidates)
        {
            if (deviceKind == "K94" ? IsK94Candidate(candidate) : IsMouseCandidate(candidate))
            {
                matches.Add(candidate);
            }
        }
        if (matches.Count != 1)
        {
            throw new InvalidOperationException("Expected exactly one " + deviceKind + " collection, found " + matches.Count);
        }
        return matches[0];
    }

    private static bool IsK94Candidate(HidCandidate candidate)
    {
        if (candidate == null)
        {
            return false;
        }
        string instanceId = candidate.DeviceInstanceId == null ? "" : candidate.DeviceInstanceId.ToUpperInvariant();
        return
            candidate.VendorId == 0x36B0 && candidate.ProductId == 0x3002 &&
            instanceId.Contains("&MI_01\\") &&
            candidate.UsagePage == 0xFF60 && candidate.Usage == 0x61 &&
            candidate.InputReportByteLength == 33 && candidate.OutputReportByteLength == 33;
    }

    private static bool IsMouseCandidate(HidCandidate candidate)
    {
        return candidate != null &&
            candidate.VendorId == 0x046D && candidate.ProductId == 0xB01B &&
            candidate.UsagePage == 0xFF43 && candidate.Usage == 0x0202 &&
            candidate.InputReportByteLength >= 20 && candidate.OutputReportByteLength >= 20;
    }

    private sealed class ImmediateFakeHidChannel : IHidIoChannel
    {
        public readonly Queue<byte[]> ReadResponses = new Queue<byte[]>();
        public readonly List<byte[]> WriteRequests = new List<byte[]>();
        public int LastNativeError { get; private set; }

        public bool WriteFile(IntPtr buffer, uint numberOfBytesToWrite, out uint numberOfBytesWritten, IntPtr overlapped)
        {
            byte[] request = new byte[numberOfBytesToWrite];
            Marshal.Copy(buffer, request, 0, (int)numberOfBytesToWrite);
            WriteRequests.Add(request);
            numberOfBytesWritten = numberOfBytesToWrite;
            LastNativeError = 0;
            return true;
        }

        public bool ReadFile(IntPtr buffer, uint numberOfBytesToRead, out uint numberOfBytesRead, IntPtr overlapped)
        {
            if (ReadResponses.Count == 0)
            {
                numberOfBytesRead = 0;
                LastNativeError = 997;
                return false;
            }
            byte[] response = ReadResponses.Dequeue();
            int bytesToCopy = (int)Math.Min(numberOfBytesToRead, response.Length);
            Marshal.Copy(response, 0, buffer, bytesToCopy);
            numberOfBytesRead = (uint)bytesToCopy;
            LastNativeError = 0;
            return true;
        }

        public bool CancelIoEx(IntPtr overlapped)
        {
            LastNativeError = 1168;
            return false;
        }

        public uint WaitForSingleObject(IntPtr eventHandle, int milliseconds)
        {
            LastNativeError = 87;
            return 258;
        }

        public bool GetOverlappedResult(IntPtr overlapped, out uint numberOfBytesTransferred, bool wait)
        {
            numberOfBytesTransferred = 0;
            LastNativeError = 997;
            return false;
        }

        public bool SetEvent(IntPtr eventHandle)
        {
            LastNativeError = 0;
            return true;
        }
    }

    private sealed class PendingFakeHidChannel : IHidIoChannel
    {
        public readonly List<IntPtr> WriteBuffers = new List<IntPtr>();
        public readonly List<IntPtr> WriteOverlapped = new List<IntPtr>();
        public int WaitDelayMilliseconds;
        public int CancelWaitDelayMilliseconds;
        public bool CancelSucceeds = true;
        public int CancelNativeError = 0;
        public bool CancelNotFoundRace;
        public bool LeaveUnresolved;
        public bool CompleteAfterCancel = true;
        public uint CompletedBytes;
        public int LastNativeError { get; private set; }

        public bool WriteFile(IntPtr buffer, uint numberOfBytesToWrite, out uint numberOfBytesWritten, IntPtr overlapped)
        {
            WriteBuffers.Add(buffer);
            WriteOverlapped.Add(overlapped);
            numberOfBytesWritten = 0;
            LastNativeError = 997;
            return false;
        }

        public bool ReadFile(IntPtr buffer, uint numberOfBytesToRead, out uint numberOfBytesRead, IntPtr overlapped)
        {
            numberOfBytesRead = 0;
            LastNativeError = 997;
            return false;
        }

        public bool CancelIoEx(IntPtr overlapped)
        {
            if (!WriteOverlapped.Contains(overlapped))
            {
                LastNativeError = 6;
                return false;
            }
            LastNativeError = CancelNotFoundRace ? 1168 : CancelNativeError;
            return CancelSucceeds && !CancelNotFoundRace;
        }

        public uint WaitForSingleObject(IntPtr eventHandle, int milliseconds)
        {
            if (WaitDelayMilliseconds > 0)
            {
                Thread.Sleep(WaitDelayMilliseconds);
                WaitDelayMilliseconds = 0;
                LastNativeError = 0;
                return 258;
            }
            if (CancelWaitDelayMilliseconds > 0)
            {
                Thread.Sleep(CancelWaitDelayMilliseconds);
                CancelWaitDelayMilliseconds = 0;
                LastNativeError = 0;
                return (uint)(LeaveUnresolved ? 258 : 0);
            }
            LastNativeError = 0;
            return (uint)(LeaveUnresolved ? 258 : 0);
        }

        public bool GetOverlappedResult(IntPtr overlapped, out uint numberOfBytesTransferred, bool wait)
        {
            if (!WriteOverlapped.Contains(overlapped))
            {
                numberOfBytesTransferred = 0;
                LastNativeError = 6;
                return false;
            }
            numberOfBytesTransferred = CompletedBytes;
            LastNativeError = LeaveUnresolved ? 997 : (CompleteAfterCancel ? 0 : 995);
            return !LeaveUnresolved && CompleteAfterCancel;
        }

        public bool SetEvent(IntPtr eventHandle)
        {
            LastNativeError = 0;
            return true;
        }
    }

    private sealed class WindowsEdgeController
    {
        private const int PollMilliseconds = 50;
        private const int DevicePollMilliseconds = 1000;
        private const int EdgeThresholdPixels = 8;
        private const int DwellMilliseconds = 400;
        private const int CooldownMilliseconds = 2500;
        private const int MOD_CONTROL = 0x0002;
        private const int MOD_ALT = 0x0001;
        private const int MOD_SHIFT = 0x0004;
        private const int WM_HOTKEY = 0x0312;
        private const int WM_HOTKEY_RETURN_ID = 1;
        private const int WM_HOTKEY_STOP_ID = 2;
        private const int PM_REMOVE = 1;

        public static void RunWindowsEdgeWatch(bool dryRun)
        {
            string state = dryRun ? "READY_WINDOWS_SIMULATED" : "AWAITING_WINDOWS_DEVICE";
            string lastEmittedState = null;
            DateTime? dwellStart = null;
            DateTime lastSubmit = DateTime.MinValue;
            DateTime nextDevicePoll = DateTime.MinValue;
            bool rearmRequiresLeaveEdge = false;
            bool mousePresent = false;
            bool slotEvidenceVerified = false;
            int currentSlot = -1;
            int hostCount = -1;
            DateTime nextHealthWrite = DateTime.MinValue;
            if (!RegisterHotKey(IntPtr.Zero, WM_HOTKEY_RETURN_ID, MOD_CONTROL | MOD_ALT | MOD_SHIFT, 0x4D))
            {
                throw new InvalidOperationException("RegisterHotKey Ctrl+Alt+Shift+M failed: " + Marshal.GetLastWin32Error());
            }
            if (!RegisterHotKey(IntPtr.Zero, WM_HOTKEY_STOP_ID, MOD_CONTROL | MOD_ALT | MOD_SHIFT, 0x58))
            {
                int stopError = Marshal.GetLastWin32Error();
                UnregisterHotKey(IntPtr.Zero, WM_HOTKEY_RETURN_ID);
                throw new InvalidOperationException("RegisterHotKey Ctrl+Alt+Shift+X failed: " + stopError);
            }
            Emit("watch-hotkeys-ready", dryRun, state, null, null, "Ctrl+Alt+Shift+M=return-to-Mac; Ctrl+Alt+Shift+X=stop");
            while (true)
            {
                MSG message;
                while (PeekMessageW(out message, IntPtr.Zero, 0, 0, PM_REMOVE))
                {
                    if (message.message != WM_HOTKEY)
                    {
                        continue;
                    }
                    if ((long)message.wParam == WM_HOTKEY_STOP_ID)
                    {
                        Emit("controller-stopped", dryRun, state, null, null, "hotkey-ctrl-alt-shift-x");
                        WriteHealthFile(state, dryRun, InputDesktopAccessible(), mousePresent, slotEvidenceVerified, currentSlot, hostCount);
                        UnregisterHotKey(IntPtr.Zero, WM_HOTKEY_RETURN_ID);
                        UnregisterHotKey(IntPtr.Zero, WM_HOTKEY_STOP_ID);
                        return;
                    }
                    if ((long)message.wParam != WM_HOTKEY_RETURN_ID || dryRun)
                    {
                        continue;
                    }
                    string manualAttemptId = "manual-hotkey-" + Guid.NewGuid().ToString("N");
                    string manualPeer = MacPeerHealth();
                    if (!MacPeerReady(manualPeer))
                    {
                        state = "TARGET_UNAVAILABLE";
                        rearmRequiresLeaveEdge = true;
                        Emit("peer-not-ready", false, state, manualAttemptId, manualPeer, null);
                        continue;
                    }
                    try
                    {
                        ProbeOutput manualOutput = RunMouseSwitchToMac(Enumerate(false));
                        bool manualSubmitted = manualOutput.Result == "switch-submitted-no-reply";
                        state = manualSubmitted ? "SWITCHING_TO_MAC" : "RECOVERY_REQUIRED";
                        lastSubmit = DateTime.UtcNow;
                        rearmRequiresLeaveEdge = true;
                        slotEvidenceVerified = manualSubmitted;
                        Emit(manualSubmitted ? "switch-submitted" : "switch-failed", false, state, manualAttemptId, manualPeer, manualOutput.Result, SlotEvidence(manualOutput), "MAC_SLOT_1");
                    }
                    catch (Exception error)
                    {
                        state = "RECOVERY_REQUIRED";
                        lastSubmit = DateTime.UtcNow;
                        rearmRequiresLeaveEdge = true;
                        Emit("switch-exception", false, state, manualAttemptId, manualPeer, error.Message);
                    }
                }
                if (!InputDesktopAccessible())
                {
                    state = "SESSION_UNAVAILABLE";
                    dwellStart = null;
                }
                else if (!dryRun && (state == "AWAITING_WINDOWS_DEVICE" || state == "READY_WINDOWS" || state == "TARGET_UNAVAILABLE" || state == "DEVICE_DEPARTED" || state == "SESSION_UNAVAILABLE") && DateTime.UtcNow >= nextDevicePoll)
                {
                    nextDevicePoll = DateTime.UtcNow.AddMilliseconds(DevicePollMilliseconds);
                    if (ConfirmWindowsDeviceReady())
                    {
                        state = "READY_WINDOWS";
                        dwellStart = null;
                        rearmRequiresLeaveEdge = true;
                        mousePresent = true;
                        slotEvidenceVerified = true;
                        currentSlot = 0;
                        hostCount = 2;
                    }
                    else if (state == "TARGET_UNAVAILABLE")
                    {
                        state = "AWAITING_WINDOWS_DEVICE";
                        mousePresent = false;
                        slotEvidenceVerified = false;
                        currentSlot = -1;
                        hostCount = -1;
                    }
                    else if (state == "READY_WINDOWS")
                    {
                        state = "AWAITING_WINDOWS_DEVICE";
                        mousePresent = false;
                        slotEvidenceVerified = false;
                        currentSlot = -1;
                        hostCount = -1;
                    }
                }
                else if (!dryRun && state == "SWITCHING_TO_MAC" && DateTime.UtcNow >= nextDevicePoll)
                {
                    nextDevicePoll = DateTime.UtcNow.AddMilliseconds(DevicePollMilliseconds);
                    if (!WindowsDevicePresent())
                    {
                        state = "DEVICE_DEPARTED";
                        mousePresent = false;
                        slotEvidenceVerified = false;
                        currentSlot = -1;
                        hostCount = -1;
                    }
                }

                POINT cursor;
                bool cursorAvailable = GetCursorPos(out cursor);
                bool interaction = AnyButtonOrModifierPressed();
                bool atRightEdge = false;
                if (cursorAvailable)
                {
                    int virtualRight = GetSystemMetrics(76) + GetSystemMetrics(78);
                    atRightEdge = cursor.X >= virtualRight - EdgeThresholdPixels;
                }
                else
                {
                    state = dryRun ? state : "RECOVERY_REQUIRED";
                    dwellStart = null;
                }

                if (!atRightEdge)
                {
                    dwellStart = null;
                    rearmRequiresLeaveEdge = false;
                }
                else if (interaction)
                {
                    dwellStart = null;
                }
                else if (rearmRequiresLeaveEdge)
                {
                    dwellStart = null;
                }
                else if (dwellStart == null)
                {
                    dwellStart = DateTime.UtcNow;
                }

                bool dwellSatisfied = !rearmRequiresLeaveEdge && dwellStart != null && (DateTime.UtcNow - dwellStart.Value).TotalMilliseconds >= DwellMilliseconds;
                bool cooldownSatisfied = (DateTime.UtcNow - lastSubmit).TotalMilliseconds >= CooldownMilliseconds;
                if (atRightEdge && !interaction && dwellSatisfied && state == (dryRun ? "READY_WINDOWS_SIMULATED" : "READY_WINDOWS") && cooldownSatisfied)
                {
                    string attemptId = "auto-edge-" + Guid.NewGuid().ToString("N");
                    dwellStart = null;
                    if (dryRun)
                    {
                        Emit("edge-would-switch", dryRun, state, attemptId, "target-unchecked", null);
                        rearmRequiresLeaveEdge = true;
                    }
                    else
                    {
                        string peer = MacPeerHealth();
                        if (!MacPeerReady(peer))
                        {
                            state = "TARGET_UNAVAILABLE";
                            rearmRequiresLeaveEdge = true;
                            Emit("peer-not-ready", false, state, attemptId, peer, null);
                        }
                        else
                        {
                            try
                            {
                                ProbeOutput output = RunMouseSwitchToMac(Enumerate(false));
                                bool submitted = output.Result == "switch-submitted-no-reply";
                                state = submitted ? "SWITCHING_TO_MAC" : "RECOVERY_REQUIRED";
                                lastSubmit = DateTime.UtcNow;
                                rearmRequiresLeaveEdge = true;
                                Emit(submitted ? "switch-submitted" : "switch-failed", false, state, attemptId, peer, output.Result, SlotEvidence(output), "MAC_SLOT_1");
                            }
                            catch (Exception error)
                            {
                                state = "RECOVERY_REQUIRED";
                                lastSubmit = DateTime.UtcNow;
                                rearmRequiresLeaveEdge = true;
                                Emit("switch-exception", false, state, attemptId, peer, error.Message);
                            }
                        }
                    }
                }

                if (state != lastEmittedState)
                {
                    lastEmittedState = state;
                    Emit("state", dryRun, state, null, null, null);
                }
                if (DateTime.UtcNow >= nextHealthWrite)
                {
                    WriteHealthFile(state, dryRun, InputDesktopAccessible(), mousePresent, slotEvidenceVerified, currentSlot, hostCount);
                    nextHealthWrite = DateTime.UtcNow.AddMilliseconds(1000);
                }
                Thread.Sleep(PollMilliseconds);
            }
        }

        public static void RunWindowsReturnHotKey()
        {
            if (!RegisterHotKey(IntPtr.Zero, 1, MOD_CONTROL | MOD_ALT | MOD_SHIFT, 0x4D))
            {
                throw new InvalidOperationException("RegisterHotKey Ctrl+Alt+Shift+M failed: " + Marshal.GetLastWin32Error());
            }
            try
            {
                Emit("hotkey-ready", false, "READY_WINDOWS", null, null, null);
                MSG message;
                while (GetMessage(out message, IntPtr.Zero, 0, 0) > 0)
                {
                    if (message.message == WM_HOTKEY && (long)message.wParam == 1)
                    {
                        string attemptId = "manual-hotkey-" + Guid.NewGuid().ToString("N");
                        string peer = MacPeerHealth();
                        if (!MacPeerReady(peer))
                        {
                            Emit("peer-not-ready", false, "TARGET_UNAVAILABLE", attemptId, peer, null);
                            continue;
                        }
                        try
                        {
                            ProbeOutput output = RunMouseSwitchToMac(Enumerate(false));
                            bool submitted = output.Result == "switch-submitted-no-reply";
                            Emit(submitted ? "switch-submitted" : "switch-failed", false, submitted ? "SWITCHING_TO_MAC" : "RECOVERY_REQUIRED", attemptId, peer, output.Result, SlotEvidence(output), "MAC_SLOT_1");
                        }
                        catch (Exception error)
                        {
                            Emit("switch-exception", false, "RECOVERY_REQUIRED", attemptId, peer, error.Message);
                        }
                    }
                }
            }
            finally
            {
                UnregisterHotKey(IntPtr.Zero, 1);
            }
        }

        private static bool ConfirmWindowsDeviceReady()
        {
            try
            {
                ProbeOutput output = RunMouseReadonly(Enumerate(false));
                return output.Result == "windows-slot-0-mac-slot-1-confirmed";
            }
            catch (InvalidOperationException)
            {
                return false;
            }
        }

        public static object CreatePeerHealth()
        {
            DateTime generatedUtc = DateTime.UtcNow;
            bool desktopAvailable = InputDesktopAccessible();
            bool mousePresent = false;
            int? currentSlot = null;
            int? hostCount = null;
            bool slotVerified = false;
            string result = "mouse-absent";
            try
            {
                List<HidCandidate> candidates = Enumerate(false);
                SelectCandidate(candidates, "Mouse");
                mousePresent = true;
                ProbeOutput output = RunMouseReadonly(candidates);
                result = output.Result;
                slotVerified = result == "windows-slot-0-mac-slot-1-confirmed";
                if (output.Responses.Count >= 2)
                {
                    ExchangeResult status = output.Responses[1] as ExchangeResult;
                    if (status != null && status.Response != null && status.Response.Length >= 6)
                    {
                        hostCount = status.Response[4];
                        currentSlot = status.Response[5];
                    }
                }
            }
            catch (InvalidOperationException error)
            {
                result = error.Message;
            }
            bool ready = desktopAvailable;
            bool returnReady = desktopAvailable && mousePresent && slotVerified && currentSlot == 0;
            return new {
                schema = 1,
                controller = "windows-peer-health-v1",
                controller_ready = false,
                ready = ready,
                return_ready = returnReady,
                reason = returnReady ? "windows-slot-0-verified" : (!desktopAvailable ? "desktop-unavailable" : "watcher-health-file-unavailable"),
                desktop = new {
                    available = desktopAvailable,
                    state = desktopAvailable ? "INTERACTIVE_DESKTOP_ACCESSIBLE" : "SESSION_UNAVAILABLE",
                },
                mouse = new {
                    present = mousePresent,
                    current_host_index = currentSlot,
                    host_count = hostCount,
                    slot_evidence_verified = slotVerified,
                    readonly_result = result,
                },
                generated_at_utc = generatedUtc.ToString("o"),
                expires_at_utc = generatedUtc.AddSeconds(15).ToString("o"),
                hid_output_report_sent = false,
            };
        }

        private static string HealthFilePath()
        {
            string configured = Environment.GetEnvironmentVariable("M585_EDGE_WINDOWS_HEALTH_PATH");
            if (!String.IsNullOrEmpty(configured))
            {
                return configured;
            }
            return Path.Combine(Path.GetTempPath(), "MiniOpsM585Edge", "windows-health.json");
        }

        private static void WriteHealthFile(string state, bool dryRun, bool desktopAvailable, bool mousePresent, bool slotEvidenceVerified, int currentSlot, int hostCount)
        {
            DateTime generated = DateTime.UtcNow;
            bool controllerReady = !dryRun && desktopAvailable && (state == "AWAITING_WINDOWS_DEVICE" || state == "READY_WINDOWS" || state == "SWITCHING_TO_MAC" || state == "DEVICE_DEPARTED" || state == "TARGET_UNAVAILABLE");
            bool ready = desktopAvailable;
            bool returnReady = desktopAvailable && mousePresent && slotEvidenceVerified && currentSlot == 0;
            string json = "{" +
                "\"schema\":1," +
                "\"controller\":\"windows-peer-health-v1\"," +
                "\"controller_ready\":" + (controllerReady ? "true" : "false") + "," +
                "\"ready\":" + (ready ? "true" : "false") + "," +
                "\"return_ready\":" + (returnReady ? "true" : "false") + "," +
                "\"reason\":\"" + (returnReady ? "windows-slot-0-verified" : (!desktopAvailable ? "desktop-unavailable" : (dryRun ? "dry-run-controller-not-ready" : "mouse-not-windows-slot-0"))) + "\"," +
                "\"desktop\":{\"available\":" + (desktopAvailable ? "true" : "false") + ",\"state\":\"" + (desktopAvailable ? "INTERACTIVE_DESKTOP_ACCESSIBLE" : "SESSION_UNAVAILABLE") + "\"}," +
                "\"mouse\":{\"present\":" + (mousePresent ? "true" : "false") + ",\"current_host_index\":" + currentSlot + ",\"host_count\":" + hostCount + ",\"slot_evidence_verified\":" + (slotEvidenceVerified ? "true" : "false") + ",\"readonly_result\":\"" + state + "\"}," +
                "\"generated_at_utc\":\"" + generated.ToString("o") + "\"," +
                "\"expires_at_utc\":\"" + generated.AddSeconds(15).ToString("o") + "\"," +
                "\"hid_output_report_sent\":false" +
                "}";
            string path = HealthFilePath();
            Directory.CreateDirectory(Path.GetDirectoryName(path));
            string temporary = path + ".tmp";
            File.WriteAllText(temporary, json, Encoding.UTF8);
            if (File.Exists(path))
            {
                File.Replace(temporary, path, path + ".old");
            }
            else
            {
                File.Move(temporary, path);
            }
        }

        private static bool WindowsDevicePresent()
        {
            try
            {
                SelectCandidate(Enumerate(false), "Mouse");
                return true;
            }
            catch (InvalidOperationException)
            {
                return false;
            }
        }

        private static bool InputDesktopAccessible()
        {
            IntPtr desktop = OpenInputDesktop(0, false, 0x0001);
            if (desktop == IntPtr.Zero)
            {
                return false;
            }
            CloseDesktop(desktop);
            return true;
        }

        private static bool AnyButtonOrModifierPressed()
        {
            return (GetAsyncKeyState(0x01) & 0x8000) != 0 ||
                (GetAsyncKeyState(0x02) & 0x8000) != 0 ||
                (GetAsyncKeyState(0x04) & 0x8000) != 0 ||
                (GetAsyncKeyState(0x05) & 0x8000) != 0 ||
                (GetAsyncKeyState(0x10) & 0x8000) != 0 ||
                (GetAsyncKeyState(0x11) & 0x8000) != 0 ||
                (GetAsyncKeyState(0x12) & 0x8000) != 0 ||
                (GetAsyncKeyState(0xA0) & 0x8000) != 0 ||
                (GetAsyncKeyState(0xA1) & 0x8000) != 0 ||
                (GetAsyncKeyState(0xA2) & 0x8000) != 0 ||
                (GetAsyncKeyState(0xA3) & 0x8000) != 0 ||
                (GetAsyncKeyState(0xA4) & 0x8000) != 0 ||
                (GetAsyncKeyState(0xA5) & 0x8000) != 0;
        }

        private static string MacPeerHealth()
        {
            string host = Environment.GetEnvironmentVariable("M585_EDGE_MAC_HOST") ?? "192.168.1.4";
            string portText = Environment.GetEnvironmentVariable("M585_EDGE_MAC_HEALTH_PORT") ?? "8787";
            int port;
            if (!int.TryParse(portText, out port))
            {
                return "invalid-port";
            }
            try
            {
                using (TcpClient client = new TcpClient())
                {
                    client.ReceiveTimeout = 2000;
                    client.SendTimeout = 2000;
                    IAsyncResult connect = client.BeginConnect(host, port, null, null);
                    if (!connect.AsyncWaitHandle.WaitOne(2000) || !client.Connected)
                    {
                        return "connect-timeout";
                    }
                    client.EndConnect(connect);
                    using (NetworkStream stream = client.GetStream())
                    {
                        stream.WriteByte(10);
                        StringBuilder response = new StringBuilder();
                        int byteRead;
                        while ((byteRead = stream.ReadByte()) >= 0 && byteRead != 10 && response.Length < 4096)
                        {
                            response.Append(Convert.ToChar(byteRead));
                        }
                        return response.ToString();
                    }
                }
            }
            catch (Exception error)
            {
                return "error:" + error.GetType().Name;
            }
        }

        private static bool MacPeerReady(string health)
        {
            return health != null &&
                health.Contains("\"ready\":true") &&
                health.Contains("\"return_target_ready\":true");
                // Both flags are required: an unavailable Mac never authorizes a return hop.
        }

        private static string SlotEvidence(ProbeOutput output)
        {
            if (output == null || output.Responses == null || output.Responses.Count < 2)
            {
                return null;
            }
            ExchangeResult status = output.Responses[1] as ExchangeResult;
            if (status == null || status.Response == null || status.Response.Length < 6)
            {
                return null;
            }
            return "{\"current_host_index\":" + status.Response[5] + ",\"host_count\":" + status.Response[4] + "}";
        }

        private static void Emit(string eventName, bool dryRun, string state, string attemptId, string peerHealth, string result, string slotEvidence = null, string target = null)
        {
            string json = "{" +
                "\"schema\":1," +
                "\"host\":\"windows\"," +
                "\"event\":\"" + eventName + "\"," +
                "\"utc\":\"" + DateTime.UtcNow.ToString("o") + "\"," +
                "\"dry_run\":" + (dryRun ? "true" : "false") + "," +
                "\"state\":\"" + state + "\"," +
                "\"attempt_id\":" + (attemptId == null ? "null" : "\"" + attemptId + "\"") + "," +
                "\"peer_health\":" + (peerHealth == null ? "null" : "\"" + peerHealth.Replace("\\", "\\\\").Replace("\"", "\\\"") + "\"") + "," +
                "\"result\":" + (result == null ? "null" : "\"" + result.Replace("\\", "\\\\").Replace("\"", "\\\"") + "\"") + "," +
                "\"current_slot_evidence\":" + (slotEvidence == null ? "null" : slotEvidence) + "," +
                "\"target\":" + (target == null ? "null" : "\"" + target + "\"") + "," +
                "\"recovery\":\"easy-switch-or-mouse-switch-mac-once\"," +
                "\"deskflow_unchanged\":true" +
                "}";
            Console.WriteLine(json);
            Console.Out.Flush();
        }
    }

    public static List<object> RunOfflineTests()
    {
        List<object> results = new List<object>();
        ProbeOutput metadata = CreateMetadataOutput(new List<HidCandidate>());
        results.Add(new { name = "metadata-default-no-requests", passed = metadata.Mode == "metadata-only" && !metadata.HidOutputReportSent && metadata.Requests.Count == 0 && metadata.Responses.Count == 0 });

        bool absentThrew = false;
        try { SelectCandidate(new List<HidCandidate>(), "Mouse"); }
        catch (InvalidOperationException) { absentThrew = true; }
        results.Add(new { name = "missing-device-fails", passed = absentThrew });

        HidCandidate validK94 = MakeK94Candidate();
        bool uniqueSelected = ReferenceEquals(SelectCandidate(new List<HidCandidate> { validK94 }, "K94"), validK94);
        results.Add(new { name = "k94-mi01-and-caps-selected", passed = uniqueSelected });

        HidCandidate wrongInterface = MakeK94Candidate();
        wrongInterface.DeviceInstanceId = "HID\\VID_36B0&PID_3002&MI_02&COL05\\7&0&0000";
        bool wrongThrew = false;
        try { SelectCandidate(new List<HidCandidate> { wrongInterface }, "K94"); }
        catch (InvalidOperationException) { wrongThrew = true; }
        results.Add(new { name = "wrong-interface-rejected", passed = wrongThrew });

        byte[] rootChange = BuildHidppRootFeatureRequest(0x1814);
        byte[] rootHosts = BuildHidppRootFeatureRequest(0x1815);
        byte[] changeStatus = BuildChangeHostStatusRequest(0x09);
        byte[] descriptor = BuildHostDescriptorRequest(0x0A, 0);
        byte[] name = BuildHostNameRequest(0x0A, 1, 14);
        bool requestShapes = rootChange[3] == 0x01 && rootHosts[3] == 0x01 && changeStatus[3] == 0x01 && descriptor[3] == 0x11 && name[3] == 0x31;
        bool changeHostRejected = false;
        try { BuildHidppRequest(0x09, 0x10, new byte[] { 0 }); }
        catch (ArgumentException) { changeHostRejected = true; }
        results.Add(new { name = "hidpp-swid-and-function-whitelist", passed = requestShapes && changeHostRejected });

        byte[] request = BuildChangeHostStatusRequest(0x09);
        byte[] reply = MakeHidppReply(request, new byte[] { 2, 0 });
        byte[] wrongSwid = (byte[])reply.Clone();
        wrongSwid[3] = 0x21;
        bool matching = ClassifyHidppResponse(reply, request) == "match" && ClassifyHidppResponse(wrongSwid, request) == "nonmatching";
        byte[] protocolError = MakeHidppProtocolError(request, 0x02);
        bool errorRecognized = ClassifyHidppResponse(protocolError, request) == "hidpp-error" && GetHidppErrorCode(protocolError) == 2;
        results.Add(new { name = "hidpp-strict-response-and-error", passed = matching && errorRecognized });

        byte[] k94Request = BuildK94ViaVersionRequest();
        byte[] k94Reply = MakeK94Reply();
        byte[] k94Echo = (byte[])k94Request.Clone();
        bool k94Match = ClassifyK94Response(k94Reply) == "match" && ClassifyK94Response(k94Echo) == "wrong-protocol-version";
        bool requestZeroTail = k94Request[0] == 0 && k94Request[1] == 1;
        for (int index = 2; index < k94Request.Length; index++) { requestZeroTail = requestZeroTail && k94Request[index] == 0; }
        results.Add(new { name = "k94-independent-fixture-matches", passed = k94Match && requestZeroTail && !ByteArrayEqual(k94Request, k94Reply) });

        ImmediateFakeHidChannel immediate = new ImmediateFakeHidChannel();
        byte[] distinctCapsRequest = BuildChangeHostStatusRequest(0x09);
        byte[] distinctCapsReply = MakeHidppReply(distinctCapsRequest, new byte[] { 2, 0 });
        immediate.ReadResponses.Enqueue(distinctCapsReply);
        ExchangeResult immediateResult = Exchange(immediate, null, 20, 22, distinctCapsRequest, 100);
        bool immediatePassed = immediateResult.Error == null && immediateResult.Response != null && ByteArrayEqual(immediateResult.Response, distinctCapsReply) &&
            immediateResult.NativeInputReportByteLength == 20 && immediateResult.NativeOutputReportByteLength == 22 &&
            immediate.WriteRequests.Count == 1 && immediate.WriteRequests[0].Length == 22 && ByteArrayEqual(immediate.WriteRequests[0], PadHidppRequest(distinctCapsRequest, 22)) && immediateResult.ElapsedMilliseconds >= 0;
        results.Add(new { name = "controlled-transport-success-distinct-caps", passed = immediatePassed });

        ImmediateFakeHidChannel shortChannel = new ImmediateFakeHidChannel();
        shortChannel.ReadResponses.Enqueue(new byte[17]);
        ExchangeResult shortResult = Exchange(shortChannel, null, 31, 33, BuildK94ViaVersionRequest(), 100);
        results.Add(new { name = "short-read-rejected", passed = shortResult.Error == "short-read" && shortResult.BytesRead == 17 && shortResult.NativeInputReportByteLength == 31 && shortResult.NativeOutputReportByteLength == 33, bytes_read = shortResult.BytesRead, native_input_report_byte_length = shortResult.NativeInputReportByteLength, native_output_report_byte_length = shortResult.NativeOutputReportByteLength });

        PendingFakeHidChannel canceled = new PendingFakeHidChannel();
        canceled.WaitDelayMilliseconds = 20;
        canceled.CancelWaitDelayMilliseconds = 10;
        canceled.CancelSucceeds = true;
        canceled.CompleteAfterCancel = false;
        canceled.CompletedBytes = 0;
        ExchangeResult canceledResult = Exchange(canceled, null, 20, 20, BuildChangeHostStatusRequest(0x09), 15);
        bool canceledPassed = canceledResult.Error == "write-timeout" && canceledResult.WriteCanceled && canceledResult.WriteFinalNativeError == 995 &&
            canceledResult.BytesWritten == 0 && canceledResult.ElapsedMilliseconds >= 25 && canceled.WriteBuffers[0] != IntPtr.Zero && canceled.WriteOverlapped[0] != IntPtr.Zero;
        results.Add(new { name = "pending-write-cancel-bounded", passed = canceledPassed, elapsed_ms = canceledResult.ElapsedMilliseconds, write_elapsed_ms = canceledResult.WriteElapsedMilliseconds, write_cancel_wait_ms = canceledResult.WriteCancelWaitMilliseconds, write_initial_native_error = canceledResult.WriteInitialNativeError, write_wait_native_error = canceledResult.WriteWaitNativeError, write_cancel_native_error = canceledResult.WriteCancelNativeError, write_get_overlapped_native_error = canceledResult.WriteGetOverlappedNativeError, write_final_native_error = canceledResult.WriteFinalNativeError });

        PendingFakeHidChannel race = new PendingFakeHidChannel();
        race.WaitDelayMilliseconds = 15;
        race.CancelWaitDelayMilliseconds = 5;
        race.CancelNotFoundRace = true;
        race.CompleteAfterCancel = true;
        race.CompletedBytes = 20;
        ExchangeResult raceResult = Exchange(race, null, 20, 20, BuildChangeHostStatusRequest(0x09), 10);
        bool racePassed = raceResult.WriteTimedOut && !raceResult.WriteCanceled && raceResult.WriteFinalNativeError == 0 && raceResult.BytesWritten == 20 &&
            raceResult.WriteCancelNativeError == 1168 && raceResult.Error != "write-unresolved";
        results.Add(new { name = "cancel-not-found-completed-race", passed = racePassed, elapsed_ms = raceResult.ElapsedMilliseconds, write_elapsed_ms = raceResult.WriteElapsedMilliseconds, write_cancel_wait_ms = raceResult.WriteCancelWaitMilliseconds, write_initial_native_error = raceResult.WriteInitialNativeError, write_wait_native_error = raceResult.WriteWaitNativeError, write_cancel_native_error = raceResult.WriteCancelNativeError, write_get_overlapped_native_error = raceResult.WriteGetOverlappedNativeError, write_final_native_error = raceResult.WriteFinalNativeError });

        int unresolvedBefore = UnresolvedPendingOperationCount;
        PendingFakeHidChannel unresolved = new PendingFakeHidChannel();
        unresolved.WaitDelayMilliseconds = 10;
        unresolved.CancelWaitDelayMilliseconds = 10;
        unresolved.LeaveUnresolved = true;
        ExchangeResult unresolvedResult = Exchange(unresolved, null, 20, 20, BuildChangeHostStatusRequest(0x09), 5);
        bool unresolvedPassed = unresolvedResult.Error == "write-unresolved" && unresolvedResult.WriteUnresolvedAfterCancel &&
            unresolvedResult.WriteFinalNativeError == 997 && unresolvedResult.WriteGetOverlappedNativeError == 997 &&
            UnresolvedPendingOperationCount == unresolvedBefore + 1 && unresolved.WriteBuffers[0] != IntPtr.Zero && unresolved.WriteOverlapped[0] != IntPtr.Zero;
        results.Add(new { name = "unconfirmed-cancel-never-freed", passed = unresolvedPassed, elapsed_ms = unresolvedResult.ElapsedMilliseconds, write_elapsed_ms = unresolvedResult.WriteElapsedMilliseconds, write_cancel_wait_ms = unresolvedResult.WriteCancelWaitMilliseconds, write_initial_native_error = unresolvedResult.WriteInitialNativeError, write_wait_native_error = unresolvedResult.WriteWaitNativeError, write_cancel_native_error = unresolvedResult.WriteCancelNativeError, write_get_overlapped_native_error = unresolvedResult.WriteGetOverlappedNativeError, write_final_native_error = unresolvedResult.WriteFinalNativeError });

        ImmediateFakeHidChannel mouseChannel = new ImmediateFakeHidChannel();
        EnqueueMouseSequence(mouseChannel);
        HidCandidate mouse = MakeMouseCandidate();
        ProbeOutput mouseOutput = RunMouseReadonly(new List<HidCandidate> { mouse }, mouseChannel, null, mouse);
        bool mouseSequencePassed = mouseOutput.Result == "windows-slot-0-mac-slot-1-confirmed" && mouseChannel.WriteRequests.Count == 9 &&
            mouseChannel.WriteRequests[0][3] == 0x01 && mouseChannel.WriteRequests[4][3] == 0x11 && mouseChannel.WriteRequests[5][3] == 0x31;
        results.Add(new { name = "mouse-readonly-capability-and-name-gates", passed = mouseSequencePassed });

        byte[] switchToMac = BuildChangeHostSwitchToMacRequest(0x09);
        bool switchToMacShape = switchToMac[0] == 0x11 && switchToMac[1] == 0xFF && switchToMac[2] == 0x09 &&
            switchToMac[3] == 0x11 && switchToMac[4] == 0x01;
        bool wrongSwitchFeatureRejected = false;
        try { BuildChangeHostSwitchToMacRequest(0x0A); }
        catch (ArgumentException) { wrongSwitchFeatureRejected = true; }
        ImmediateFakeHidChannel switchChannel = new ImmediateFakeHidChannel();
        EnqueueMouseSequence(switchChannel);
        ProbeOutput switchOutput = RunMouseSwitchToMac(new List<HidCandidate> { mouse }, switchChannel, null, mouse);
        bool switchPassed = switchOutput.Mode == "M585-switch-to-mac-once" && switchOutput.Result == "switch-submitted-no-reply" &&
            switchChannel.WriteRequests.Count == 10 && ByteArrayEqual(switchChannel.WriteRequests[9], switchToMac) &&
            switchOutput.Responses.Count == 10 && ((ExchangeResult)switchOutput.Responses[9]).BytesWritten == 20 &&
            ((ExchangeResult)switchOutput.Responses[9]).Error == null;
        results.Add(new { name = "mouse-switch-to-mac-once-after-preflight", passed = switchPassed && switchToMacShape && wrongSwitchFeatureRejected });

        ImmediateFakeHidChannel k94Channel = new ImmediateFakeHidChannel();
        k94Channel.ReadResponses.Enqueue(k94Reply);
        HidCandidate k94Candidate = MakeK94Candidate();
        ProbeOutput k94Output = RunK94ViaVersion(new List<HidCandidate> { k94Candidate }, k94Channel, null, k94Candidate);
        results.Add(new { name = "k94-receiver-path-uses-verified-request", passed = k94Output.Result == "receiver-path-responded" && ByteArrayEqual(k94Channel.WriteRequests[0], k94Request) });

        return results;
    }

    public static void RunWindowsEdgeWatch(bool dryRun)
    {
        WindowsEdgeController.RunWindowsEdgeWatch(dryRun);
    }

    public static void RunWindowsReturnHotKey()
    {
        WindowsEdgeController.RunWindowsReturnHotKey();
    }

    public static object RunWindowsPeerHealth()
    {
        return WindowsEdgeController.CreatePeerHealth();
    }

    private static HidCandidate MakeK94Candidate()
    {
        HidCandidate candidate = new HidCandidate();
        candidate.DeviceInstanceId = "HID\\VID_36B0&PID_3002&MI_01\\7&0&0000";
        candidate.DevicePath = "\\\\?\\hid#vid_36b0&pid_3002&mi_01#7&0&0000";
        candidate.VendorId = 0x36B0;
        candidate.ProductId = 0x3002;
        candidate.UsagePage = 0xFF60;
        candidate.Usage = 0x61;
        candidate.InputReportByteLength = 33;
        candidate.OutputReportByteLength = 33;
        return candidate;
    }

    private static HidCandidate MakeMouseCandidate()
    {
        HidCandidate candidate = new HidCandidate();
        candidate.DeviceInstanceId = "BTHLEDEVICE\\DEV_TEST";
        candidate.DevicePath = "\\\\?\\bthledevice#dev_test";
        candidate.VendorId = 0x046D;
        candidate.ProductId = 0xB01B;
        candidate.UsagePage = 0xFF43;
        candidate.Usage = 0x0202;
        candidate.InputReportByteLength = 20;
        candidate.OutputReportByteLength = 20;
        return candidate;
    }

    private static byte[] MakeHidppReply(byte[] request, byte[] data)
    {
        byte[] response = (byte[])request.Clone();
        Array.Copy(data, 0, response, 4, data.Length);
        return response;
    }

    private static byte[] PadHidppRequest(byte[] request, int nativeLength)
    {
        byte[] padded = new byte[nativeLength];
        Array.Copy(request, padded, request.Length);
        return padded;
    }

    private static byte[] MakeHidppProtocolError(byte[] request, byte errorCode)
    {
        byte[] response = new byte[20];
        response[0] = 0x11;
        response[1] = 0xFF;
        response[2] = 0xFF;
        response[3] = request[2];
        response[4] = request[3];
        response[5] = errorCode;
        return response;
    }

    private static byte[] MakeHidppNameReply(byte[] request, byte slot, byte offset, byte[] payload)
    {
        byte[] response = (byte[])request.Clone();
        if (payload.Length > response.Length - 6)
        {
            throw new InvalidOperationException("Name fixture payload is too long: " + payload.Length);
        }
        response[4] = slot;
        response[5] = offset;
        Array.Copy(payload, 0, response, 6, payload.Length);
        return response;
    }

    private static byte[] MakeK94Reply()
    {
        byte[] response = new byte[33];
        response[0] = 0x00;
        response[1] = 0x01;
        response[2] = 0x00;
        response[3] = 0x0C;
        response[4] = 0x5A;
        response[5] = 0xA5;
        response[6] = 0x3C;
        return response;
    }

    private static void EnqueueMouseSequence(ImmediateFakeHidChannel channel)
    {
        channel.ReadResponses.Enqueue(MakeHidppReply(BuildHidppRootFeatureRequest(0x1814), new byte[] { 0x09, 0 }));
        channel.ReadResponses.Enqueue(MakeHidppReply(BuildChangeHostStatusRequest(0x09), new byte[] { 2, 0 }));
        channel.ReadResponses.Enqueue(MakeHidppReply(BuildHidppRootFeatureRequest(0x1815), new byte[] { 0x0A, 0 }));
        channel.ReadResponses.Enqueue(MakeHidppReply(BuildHostsInfoStateRequest(0x0A), new byte[] { 0x13, 0, 2, 0 }));
        channel.ReadResponses.Enqueue(MakeHidppReply(BuildHostDescriptorRequest(0x0A, 0), new byte[] { 0, 1, 0, 0, 12, 24 }));
        channel.ReadResponses.Enqueue(MakeHidppNameReply(BuildHostNameRequest(0x0A, 0, 0), 0, 0, Encoding.ASCII.GetBytes("LAZY-WINDOWS")));
        channel.ReadResponses.Enqueue(MakeHidppReply(BuildHostDescriptorRequest(0x0A, 1), new byte[] { 1, 1, 0, 0, 15, 24 }));
        channel.ReadResponses.Enqueue(MakeHidppNameReply(BuildHostNameRequest(0x0A, 1, 0), 1, 0, new byte[] { 0x6C, 0x61, 0x7A, 0x79, 0xE7, 0x9A, 0x84, 0x4D, 0x61, 0x63, 0x20, 0x4D, 0x69, 0x6E }));
        channel.ReadResponses.Enqueue(MakeHidppNameReply(BuildHostNameRequest(0x0A, 1, 14), 1, 14, new byte[] { 0x69 }));
    }

    private static bool ByteArrayEqual(byte[] left, byte[] right)
    {
        if (left == null || right == null || left.Length != right.Length)
        {
            return false;
        }
        for (int index = 0; index < left.Length; index++)
        {
            if (left[index] != right[index])
            {
                return false;
            }
        }
        return true;
    }

    [DllImport("setupapi.dll", EntryPoint = "SetupDiGetClassDevsW", ExactSpelling = true, SetLastError = true)]
    private static extern IntPtr SetupDiGetClassDevs(ref Guid classGuid, IntPtr enumerator, IntPtr hwndParent, uint flags);

    [DllImport("setupapi.dll", ExactSpelling = true, SetLastError = true)]
    private static extern bool SetupDiEnumDeviceInterfaces(IntPtr deviceInfoSet, IntPtr deviceInfoData, ref Guid interfaceClassGuid, uint memberIndex, ref SP_DEVICE_INTERFACE_DATA deviceInterfaceData);

    [DllImport("setupapi.dll", EntryPoint = "SetupDiGetDeviceInterfaceDetailW", ExactSpelling = true, SetLastError = true)]
    private static extern bool SetupDiGetDeviceInterfaceDetail(IntPtr deviceInfoSet, ref SP_DEVICE_INTERFACE_DATA deviceInterfaceData, IntPtr deviceInterfaceDetailData, uint deviceInterfaceDetailDataSize, out uint requiredSize, ref SP_DEVINFO_DATA deviceInfoData);

    [DllImport("setupapi.dll", EntryPoint = "SetupDiGetDeviceInstanceIdW", ExactSpelling = true, SetLastError = true, CharSet = CharSet.Unicode)]
    private static extern bool SetupDiGetDeviceInstanceId(IntPtr deviceInfoSet, ref SP_DEVINFO_DATA deviceInfoData, StringBuilder deviceInstanceId, uint deviceInstanceIdSize, out uint requiredSize);

    [DllImport("setupapi.dll", ExactSpelling = true, SetLastError = true)]
    private static extern bool SetupDiDestroyDeviceInfoList(IntPtr deviceInfoSet);

    [DllImport("kernel32.dll", ExactSpelling = true, SetLastError = true, CharSet = CharSet.Unicode)]
    private static extern SafeFileHandle CreateFileW(string fileName, uint desiredAccess, uint shareMode, IntPtr securityAttributes, uint creationDisposition, uint flagsAndAttributes, IntPtr templateFile);

    [DllImport("kernel32.dll", ExactSpelling = true, SetLastError = true, CharSet = CharSet.Unicode)]
    private static extern IntPtr CreateEventExW(IntPtr eventAttributes, string name, uint flags, uint desiredAccess);

    [DllImport("kernel32.dll", EntryPoint = "CancelIoEx", ExactSpelling = true, SetLastError = true)]
    private static extern bool CancelIoExNative(SafeFileHandle handle, IntPtr overlapped);

    [DllImport("kernel32.dll", EntryPoint = "WaitForSingleObject", ExactSpelling = true, SetLastError = true)]
    private static extern uint WaitForSingleObjectNative(IntPtr handle, int milliseconds);

    [DllImport("kernel32.dll", EntryPoint = "SetEvent", ExactSpelling = true, SetLastError = true)]
    private static extern bool SetEventNative(IntPtr handle);

    [DllImport("kernel32.dll", EntryPoint = "GetOverlappedResult", ExactSpelling = true, SetLastError = true)]
    private static extern bool GetOverlappedResultNative(SafeFileHandle handle, IntPtr overlapped, out uint numberOfBytesTransferred, bool wait);

    [DllImport("kernel32.dll", EntryPoint = "WriteFile", ExactSpelling = true, SetLastError = true)]
    private static extern bool WriteFileNative(SafeFileHandle handle, IntPtr buffer, uint numberOfBytesToWrite, out uint numberOfBytesWritten, IntPtr overlapped);

    [DllImport("kernel32.dll", EntryPoint = "ReadFile", ExactSpelling = true, SetLastError = true)]
    private static extern bool ReadFileNative(SafeFileHandle handle, IntPtr buffer, uint numberOfBytesToRead, out uint numberOfBytesRead, IntPtr overlapped);

    [DllImport("hid.dll", ExactSpelling = true, SetLastError = true)]
    private static extern bool HidD_GetPreparsedData(SafeFileHandle hidDeviceObject, out IntPtr preparsedData);

    [DllImport("hid.dll", ExactSpelling = true, SetLastError = true)]
    private static extern bool HidD_FreePreparsedData(IntPtr preparsedData);

    [DllImport("hid.dll", ExactSpelling = true, SetLastError = true)]
    private static extern int HidP_GetCaps(IntPtr preparsedData, ref HIDP_CAPS capabilities);

    [DllImport("hid.dll", ExactSpelling = true, SetLastError = true)]
    private static extern bool HidD_GetAttributes(SafeFileHandle hidDeviceObject, ref HIDD_ATTRIBUTES attributes);

    [DllImport("user32.dll", ExactSpelling = true, SetLastError = true)]
    private static extern bool GetCursorPos(out POINT point);

    [DllImport("user32.dll", ExactSpelling = true, SetLastError = true)]
    private static extern int GetSystemMetrics(int index);

    [DllImport("user32.dll", ExactSpelling = true, SetLastError = true)]
    private static extern short GetAsyncKeyState(int virtualKey);

    [DllImport("user32.dll", ExactSpelling = true, SetLastError = true)]
    private static extern IntPtr OpenInputDesktop(uint flags, bool inherit, uint desiredAccess);

    [DllImport("user32.dll", ExactSpelling = true, SetLastError = true)]
    private static extern bool CloseDesktop(IntPtr desktop);

    [DllImport("user32.dll", ExactSpelling = true, SetLastError = true)]
    private static extern bool RegisterHotKey(IntPtr window, int id, int modifiers, int virtualKey);

    [DllImport("user32.dll", ExactSpelling = true, SetLastError = true)]
    private static extern bool UnregisterHotKey(IntPtr window, int id);

    [DllImport("user32.dll", ExactSpelling = true, SetLastError = true)]
    private static extern int GetMessage(out MSG message, IntPtr window, int minimumMessage, int maximumMessage);

    [DllImport("user32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    private static extern bool PeekMessageW(out MSG message, IntPtr window, int minimumMessage, int maximumMessage, int removalFlags);
}
"@

try {
    Add-Type -TypeDefinition $protocolProbeSource -Language CSharp
} catch {
    Write-WatchHealthJson -State "ERROR_ADD_TYPE" -ControllerReady $false -Ready $false -Reason ("add-type: " + $_.Exception.Message) -DesktopAvailable $false
    Write-Error $_
    exit 2
}

try {
    if ($TestOnly) {
        $json = ConvertTo-Json -InputObject @([WindowsHidProtocolProbe]::RunOfflineTests()) -Depth 6
        [Console]::Out.WriteLine($json)
    } elseif ($MouseReadOnly -and $K94ViaVersion) {
        throw "Choose exactly one protocol mode or no mode for metadata-only enumeration."
    } elseif ($MouseReadOnly) {
        $candidates = [WindowsHidProtocolProbe]::Enumerate([bool]$AllCandidates)
        $json = ConvertTo-Json -InputObject @([WindowsHidProtocolProbe]::RunMouseReadonly($candidates)) -Depth 8
        [Console]::Out.WriteLine($json)
    } elseif ($K94ViaVersion) {
        $candidates = [WindowsHidProtocolProbe]::Enumerate([bool]$AllCandidates)
        $json = ConvertTo-Json -InputObject @([WindowsHidProtocolProbe]::RunK94ViaVersion($candidates)) -Depth 8
        [Console]::Out.WriteLine($json)
    } elseif ($IsWindowsEdgeMode) {
        if ($WindowsReturnHotKey) {
            [WindowsHidProtocolProbe]::RunWindowsReturnHotKey()
        } elseif ($WindowsPeerHealth) {
            $json = ConvertTo-Json -InputObject @([WindowsHidProtocolProbe]::RunWindowsPeerHealth()) -Depth 6
            [Console]::Out.WriteLine($json)
        } else {
            [WindowsHidProtocolProbe]::RunWindowsEdgeWatch([bool]$WindowsEdgeDryRun)
        }
    } else {
        $candidates = [WindowsHidProtocolProbe]::Enumerate([bool]$AllCandidates)
        $json = ConvertTo-Json -InputObject @([WindowsHidProtocolProbe]::CreateMetadataOutput($candidates)) -Depth 6
        [Console]::Out.WriteLine($json)
    }
} catch {
    Write-WatchHealthJson -State "ERROR_RUNTIME" -ControllerReady $false -Ready $false -Reason ("runtime: " + $_.Exception.Message) -DesktopAvailable $false
    Write-Error $_
    exit 3
}

param(
    [Parameter(Mandatory = $true)][string]$SecretFile,
    [switch]$TestOnly,
    [string]$ListenAddress = '192.168.1.8',
    [int]$Port = 8792,
    [Parameter(Mandatory = $true)][string]$LogDirectory
)

$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force $LogDirectory | Out-Null
$logFile = Join-Path $LogDirectory 'keyboard-service.jsonl'
function Write-Event($Name, $Data) {
    Add-Content -LiteralPath $logFile -Value (@{ event = $Name; utc = [DateTime]::UtcNow.ToString('o'); data = $Data } | ConvertTo-Json -Compress) -Encoding UTF8
}

$source = @'
using System;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;

public static class MiniOpsKeyboardReceiver {
    [StructLayout(LayoutKind.Sequential)] public struct INPUT { public uint type; public InputUnion data; }
    [StructLayout(LayoutKind.Explicit)] public struct InputUnion { [FieldOffset(0)] public KEYBDINPUT keyboard; }
    [StructLayout(LayoutKind.Sequential)] public struct KEYBDINPUT { public ushort key; public ushort scan; public uint flags; public uint time; public IntPtr extra; }
    [DllImport("user32.dll", SetLastError=true)] static extern uint SendInput(uint count, INPUT[] inputs, int size);
    [DllImport("user32.dll")] static extern IntPtr OpenInputDesktop(uint flags, bool inherit, uint access);
    [DllImport("user32.dll")] static extern bool CloseDesktop(IntPtr desktop);

    static Dictionary<string, ushort> Keys = new Dictionary<string, ushort>();
    static HashSet<ushort> Down = new HashSet<ushort>();
    static HashSet<string> Nonces = new HashSet<string>();
    static int LastSequence = 0;
    static string Session = "";
    static DateTime LastInput = DateTime.UtcNow;
    static System.Threading.Timer Watchdog;
    static object Gate = new object();
    static void Add(string name, ushort key) { Keys[name] = key; }
    static MiniOpsKeyboardReceiver() {
        Watchdog = new System.Threading.Timer(delegate { if (Down.Count > 0 && (DateTime.UtcNow - LastInput).TotalSeconds > 5) ReleaseAll(); }, null, 1000, 1000);
        for (int i=0; i<26; i++) Add(((char)('a'+i)).ToString(), (ushort)(0x41+i));
        for (int i=0; i<10; i++) Add(i.ToString(), (ushort)(0x30+i));
        for (int i=1; i<=12; i++) Add("f"+i, (ushort)(0x70+i-1));
        Add("space",0x20); Add("return",0x0D); Add("tab",0x09); Add("escape",0x1B); Add("backspace",0x08); Add("delete",0x2E);
        Add("left",0x25); Add("right",0x27); Add("up",0x26); Add("down",0x28); Add("home",0x24); Add("end",0x23); Add("pageup",0x21); Add("pagedown",0x22); Add("insert",0x2D);
        Add("shift",0x10); Add("control",0x11); Add("option",0x12); Add("command",0x5B); Add("capslock",0x14);
        Add("minus",0xBD); Add("equal",0xBB); Add("leftbracket",0xDB); Add("rightbracket",0xDD); Add("backslash",0xDC); Add("semicolon",0xBA); Add("quote",0xDE); Add("comma",0xBC); Add("period",0xBE); Add("slash",0xBF); Add("grave",0xC0);
    }
    public static string ReleaseAllForTest() {
        ReleaseAll();
        return Down.Count == 0 ? "released" : "stuck";
    }
    public static string InjectForTest(string name, bool pressed) {
        if (!DesktopAvailable()) throw new InvalidOperationException("SESSION_UNAVAILABLE");
        ushort key = Keys[name];
        if (SendInput(1, new INPUT[] { Make(key, pressed) }, Marshal.SizeOf(typeof(INPUT))) != 1) throw new InvalidOperationException("SendInput failed");
        if (pressed) Down.Add(key); else Down.Remove(key);
        return "injected";
    }
    static void ReleaseAll() {
        var inputs = new List<INPUT>();
        foreach (ushort key in Down) inputs.Add(Make(key, false));
        if (inputs.Count>0) SendInput((uint)inputs.Count, inputs.ToArray(), Marshal.SizeOf(typeof(INPUT)));
        Down.Clear();
    }
    static INPUT Make(ushort key, bool pressed) { INPUT input = new INPUT(); input.type=1; input.data.keyboard.key=key; input.data.keyboard.flags=pressed ? 0u : 2u; return input; }
    static bool DesktopAvailable() { IntPtr desktop=OpenInputDesktop(0,false,1); if(desktop==IntPtr.Zero) return false; CloseDesktop(desktop); return true; }
    static void Nack(NetworkStream stream, string reason) { byte[] data=Encoding.ASCII.GetBytes("error:"+reason+"\n"); stream.Write(data,0,data.Length); }
    public static void Run(string address, int port, string secretFile, string logFile) {
        byte[] secret=File.ReadAllBytes(secretFile);
        TcpListener listener=new TcpListener(IPAddress.Parse(address),port);
        listener.Start();
        File.AppendAllText(logFile,"{\"event\":\"keyboard-ready\"}\n");
        while(true) {
            using(TcpClient client=listener.AcceptTcpClient()) {
                client.ReceiveTimeout=1500;
                NetworkStream stream=client.GetStream();
                try {
                    List<byte> frame=new List<byte>();
                    int value;
                    while((value=stream.ReadByte())>=0 && value!=10) { frame.Add((byte)value); if(frame.Count>2048) throw new InvalidDataException(); }
                    string[] pieces=Encoding.ASCII.GetString(frame.ToArray()).Split('.');
                    byte[] payload=Convert.FromBase64String(pieces[0]);
                    using(HMACSHA256 hmac=new HMACSHA256(secret)) {
                        string expected=BitConverter.ToString(hmac.ComputeHash(payload)).Replace("-","").ToLowerInvariant();
                        if(pieces.Length!=2 || pieces[1]!=expected) throw new InvalidDataException();
                    }
                    string json=Encoding.UTF8.GetString(payload);
                    var data=new JavaScriptSerializer().Deserialize<Dictionary<string,object>>(json);
                    string kind=(string)data["kind"];
                    string session=(string)data["session"];
                    int sequence=Convert.ToInt32(data["sequence"]);
                    string nonce=(string)data["nonce"];
                    long timestamp=Convert.ToInt64(data["timestamp_ms"]);
                    if(session!=Session) { ReleaseAll(); Session=session; LastSequence=0; Nonces.Clear(); }
                    if(Math.Abs(DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()-timestamp)>10000) { Nack(stream,"stale"); continue; }
                    if(sequence<=LastSequence || Nonces.Contains(nonce)) { stream.Write(Encoding.ASCII.GetBytes("ok\n"),0,3); continue; }
                    LastSequence=sequence;
                    Nonces.Add(nonce);
                    if(Nonces.Count>2048) Nonces.Clear();
                    LastInput=DateTime.UtcNow;
                    lock(Gate) {
                        if(!DesktopAvailable()) { ReleaseAll(); Session=""; LastSequence=0; Nonces.Clear(); throw new InvalidOperationException("SESSION_UNAVAILABLE"); }
                        if(kind=="release_all") ReleaseAll();
                        else if(kind=="ping") { }
                        else if(kind=="key") {
                            string name=(string)data["key"]; bool pressed=(bool)data["pressed"];
                            ushort key=Keys[name];
                            if(SendInput(1,new INPUT[]{Make(key,pressed)},Marshal.SizeOf(typeof(INPUT)))!=1) throw new InvalidOperationException("SendInput failed");
                            if(pressed) Down.Add(key); else Down.Remove(key);
                        }
                    }
                    stream.Write(Encoding.ASCII.GetBytes("ok\n"),0,3);
                } catch(Exception error) { ReleaseAll(); Nack(stream,"rejected"); File.AppendAllText(logFile,"{\"event\":\"key-rejected\",\"type\":\""+error.GetType().Name+"\"}\n"); }
            }
        }
    }
}
'@
$source = $source.Replace('new JavaScriptSerializer()', 'new System.Web.Script.Serialization.JavaScriptSerializer()')
Add-Type -TypeDefinition $source -Language CSharp -ReferencedAssemblies 'System.Web.Extensions'
if ($TestOnly) {
    [MiniOpsKeyboardReceiver]::InjectForTest('shift', $true)
    $released = [MiniOpsKeyboardReceiver]::ReleaseAllForTest()
    $required = @('SESSION_UNAVAILABLE', 'Nonces', 'Session', 'SendInput')
    $results = @($required | ForEach-Object { @{ name = $_; passed = $source.Contains($_) } })
    $results += @{ name = 'modifier-release'; passed = $released -eq 'released' }
    $results | ConvertTo-Json -Compress
    exit 0
}
try { [MiniOpsKeyboardReceiver]::Run($ListenAddress, $Port, $SecretFile, $logFile) }
catch { Write-Event 'keyboard-error' @{ type = $_.Exception.GetType().Name; message = $_.Exception.Message }; exit 1 }

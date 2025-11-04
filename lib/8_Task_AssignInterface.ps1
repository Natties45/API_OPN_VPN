# Task 8: Assign Interface (via SSH)
$TargetHost = $State.Profile.SshHost
$SshUser    = $State.Profile.SshUser
$SshPass    = $State.Profile.SshPass
$Descr      = $State.Settings.InterfaceDesc

# --- 1. Ensure Posh-SSH module ---
Ensure-PoshSSH

# --- 2. Remote PHP Script ---
$phpCode = @'
<?php
/*
 * assign-ovpns.php (no shebang, no BOM)
 * - Auto-discover unassigned ovpns* devices
 * - Backup /conf/config.xml
 * - Add new <optN> entries (no gap reuse) with <if>ovpnsX</if>, <descr>, <enable/>
 * - Save atomically (write .new then rename)
 * - Validate XML before commit; rollback to backup on failure
 * - Print lines: NEW <dev> <optN> | EXIST <dev> <optN> | SKIP <dev> NO_DEV | BACKUP <path> | SUMMARY ...
 *
 * Usage: php /tmp/assign-ovpns.php "<DESC>"
 */

function bail(string $msg, int $code=1): void { fwrite(STDERR, "$msg\n"); exit($code); }
if ($argc < 2) bail("USAGE: assign-ovpns.php <DESC>", 99);

$desc = $argv[1];
$cfg  = '/conf/config.xml';
$tmp  = $cfg . '.new';
$bk   = $cfg . '.' . date('Ymd_His') . '.bak';

// 1) Backup first
if (!@copy($cfg, $bk)) bail("BACKUP_FAIL");
echo "BACKUP $bk\n";

// 2) Parse current config
libxml_use_internal_errors(true);
$xml = simplexml_load_file($cfg);
if (!$xml) bail("XML_PARSE_FAIL");
if (!isset($xml->interfaces)) bail("NO_INTERFACES_TAG");
$ifs = $xml->interfaces;

// 3) Build maps: existing opt indices, device->opt
$dev2opt = [];
$usedNums = [];
foreach ($ifs->children() as $child) {
    $name = $child->getName(); // optN/lan/wan etc.
    if (preg_match('/^opt(\d+)$/', $name, $m)) {
        $usedNums[(int)$m[1]] = true;
        $ifdev = (string)$child->if;
        if ($ifdev !== '') $dev2opt[$ifdev] = $name;
    }
}

// 4) Discover all ovpns* from system
$iflist = trim(shell_exec('/sbin/ifconfig -l 2>/dev/null') ?? '');
$allifs = preg_split('/\s+/', $iflist, -1, PREG_SPLIT_NO_EMPTY);
$ovpns = [];
foreach ($allifs as $d) {
    if (preg_match('/^ovpns\d+$/', $d)) $ovpns[] = $d;
}
if (!$ovpns) { echo "SUMMARY ADDED: EXIST: (no ovpns found)\n"; exit(0); }

// helper: pick next opt (no gap reuse to avoid remapping surprises)
$chooseNext = function(array $used): string {
    $max = 0; foreach ($used as $k => $_) if ($k > $max) $max = $k;
    return 'opt'.($max + 1);
};

$added = []; $exist = [];

// 5) For each ovpns, add if not yet assigned
foreach ($ovpns as $dev) {
    // verify device exists
    $rc = 1;
    @exec('/sbin/ifconfig '.escapeshellarg($dev).' >/dev/null 2>&1', $_o, $rc);
    if ($rc !== 0) { echo "SKIP $dev NO_DEV\n"; continue; }

    if (isset($dev2opt[$dev])) {
        $opt = $dev2opt[$dev];
        echo "EXIST $dev $opt\n";
        $exist[$opt] = true;
        continue;
    }

    $opt = $chooseNext($usedNums);
    $node = $ifs->addChild($opt);
    $node->addChild('if', $dev);
    $node->addChild('descr', $desc);
    $node->addChild('enable');
    if (preg_match('/^opt(\d+)$/', $opt, $m)) $usedNums[(int)$m[1]] = true;

    echo "NEW $dev $opt\n";
    $added[$opt] = true;
}

// 6) Save atomically
$dom = dom_import_simplexml($xml)->ownerDocument;
$dom->formatOutput = true;
if ($dom->save($tmp) === false) { @copy($bk, $cfg); bail("XML_SAVE_FAIL"); }

// 7) Validate written XML
$verify = simplexml_load_file($tmp);
if (!$verify) { @copy($bk, $cfg); bail("XML_INVALID_ROLLBACK"); }

// 8) Commit
if (!@rename($tmp, $cfg)) { @copy($bk, $cfg); bail("RENAME_FAIL"); }

echo "SUMMARY ADDED:" . implode(' ', array_keys($added)) . " EXIST:" . implode(' ', array_keys($exist)) . "\n";
exit(0);
'@

# --- 3. Build a temp file and upload via SSH ---
$localPhp = Join-Path $State.TempDir "assign-ovpns.php"
Set-Content -Path $localPhp -Value $phpCode -Encoding Ascii -Force

$sec  = ConvertTo-SecureString $SshPass -AsPlainText -Force
$cred = New-Object System.Management.Automation.PSCredential ($SshUser,$sec)

$sess = $null
try {
  Write-Host "  Connecting to SSH $SshUser@$TargetHost..."
  $sess = New-SSHSession -ComputerName $TargetHost -Credential $cred -AcceptKey
  Invoke-SSHCommand -SessionId $sess.SessionId -Command 'mkdir -p /tmp' | Out-Null
  Set-SCPItem -ComputerName $TargetHost -Credential $cred -Path $localPhp -Destination "/tmp" -AcceptKey
  Invoke-SSHCommand -SessionId $sess.SessionId -Command "chmod +x /tmp/assign-ovpns.php" | Out-Null
  Write-Host "  Uploaded PHP script to /tmp/assign-ovpns.php"

  $cmd = "/usr/bin/lockf -k -t 60 /tmp/assign-if.lock /usr/local/bin/php /tmp/assign-ovpns.php " + ("'{0}'" -f $Descr)
  Write-Host "  Executing remote script..."
  $res  = Invoke-SSHCommand -SessionId $sess.SessionId -Command $cmd

  $stdout = ($res.Output | Where-Object { $_ } | ForEach-Object { $_.ToString().Trim() }) -join "`n"
  if ($stdout) {
    Write-Host "  ---- Remote Output ----`n$stdout`n  ---------------------" -ForegroundColor DarkGray
  } else {
    Write-Warning "  No output from remote script."
  }

  $newOpts   = [regex]::Matches($stdout, '(?m)^NEW\s+\S+\s+(opt\d+)$')   | ForEach-Object { $_.Groups[1].Value } | Select-Object -Unique
  $existOpts = [regex]::Matches($stdout, '(?m)^EXIST\s+\S+\s+(opt\d+)$') | ForEach-Object { $_.Groups[1].Value } | Select-Object -Unique
  $allOpts   = @($newOpts + $existOpts) | Select-Object -Unique

  if (-not $allOpts -or $allOpts.Count -eq 0) {
    Write-Host "  No new or existing interfaces found to apply."
  } else {
    Write-Host "  Applying configuration for interfaces: $($allOpts -join ', ')"
    foreach ($optId in $allOpts) {
      $apply = Invoke-SSHCommand -SessionId $sess.SessionId -Command "/usr/local/sbin/configctl interface reconfigure $optId"
      Write-Host ("  Apply {0}: {1}" -f $optId, ($apply.Output -join ' ')) -ForegroundColor Yellow
    }
  }
  Write-Host ("  Interface assignment finished. New: {0} | Existing: {1}" -f (($newOpts -join ', ')), (($existOpts -join ', ')))
}
finally {
  if ($sess) {
    try { Invoke-SSHCommand -SessionId $sess.SessionId -Command "rm -f /tmp/assign-ovpns.php" | Out-Null } catch {}
    Remove-SSHSession -SessionId $sess.SessionId | Out-Null
  }
  Remove-Item $localPhp -Force -ErrorAction SilentlyContinue
}
Write-Host "[Task 8/9] Complete" -ForegroundColor Green
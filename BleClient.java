package org.bleremote;

import android.bluetooth.*;
import android.bluetooth.le.*;
import android.content.Context;
import android.location.LocationManager;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.os.ParcelUuid;
import java.util.*;
import java.util.concurrent.ConcurrentLinkedDeque;

/**
 * Sender BLE client (hardened).
 * - No exception can escape to Python or to a Binder thread (an uncaught one kills the whole app).
 * - Missing permission / Bluetooth off / Location off are reported as states instead of crashing.
 * - Only the FIRST scan result is connected to (scan callbacks can fire many times).
 */
public class BleClient {
    static final UUID SVC = UUID.fromString("12345678-1234-5678-1234-56789abcdef0");
    static final UUID W = UUID.fromString("12345678-1234-5678-1234-56789abcdef1");
    static final UUID N = UUID.fromString("12345678-1234-5678-1234-56789abcdef2");
    static final UUID CCCD = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb");

    Context ctx; BluetoothAdapter ad; BluetoothGatt gatt; BluetoothGattCharacteristic wc;
    volatile String state = "idle"; volatile int mtu = 23;
    boolean writing = false;
    volatile boolean found = false;
    volatile boolean discovering = false;
    final Handler main = new Handler(Looper.getMainLooper());
    final ConcurrentLinkedDeque<byte[]> out = new ConcurrentLinkedDeque<>();
    final ConcurrentLinkedDeque<byte[]> in = new ConcurrentLinkedDeque<>();

    public BleClient(Context c) {
        ctx = c;
        try {
            BluetoothManager m = (BluetoothManager) c.getSystemService(Context.BLUETOOTH_SERVICE);
            ad = (m != null) ? m.getAdapter() : null;
        } catch (Exception e) { ad = null; }
    }

    boolean locationOn() {
        try {
            LocationManager lm = (LocationManager) ctx.getSystemService(Context.LOCATION_SERVICE);
            if (lm == null) return true;
            if (Build.VERSION.SDK_INT >= 28) return lm.isLocationEnabled();
            return lm.isProviderEnabled(LocationManager.GPS_PROVIDER) || lm.isProviderEnabled(LocationManager.NETWORK_PROVIDER);
        } catch (Exception e) { return true; }
    }

    void stopScan() {
        try {
            if (ad != null) {
                BluetoothLeScanner sc = ad.getBluetoothLeScanner();
                if (sc != null) sc.stopScan(scanCb);
            }
        } catch (Exception e) { }
    }

    void closeGatt() {
        BluetoothGatt g = gatt;
        gatt = null; wc = null; writing = false; discovering = false;
        out.clear();
        try { if (g != null) { g.disconnect(); g.close(); } } catch (Exception e) { }
    }

    public void connect() {
        try {
            if (ad == null || !ad.isEnabled()) { state = "bt_off"; return; }
            // Android 10/11: scan results are empty unless Location is ON and the permission is granted
            if (Build.VERSION.SDK_INT < 31 && !locationOn()) { state = "location_off"; return; }
            stopScan();
            closeGatt();
            BluetoothLeScanner sc = ad.getBluetoothLeScanner();
            if (sc == null) { state = "bt_off"; return; }
            found = false;
            state = "scanning";
            ScanFilter f = new ScanFilter.Builder().setServiceUuid(new ParcelUuid(SVC)).build();
            ScanSettings s = new ScanSettings.Builder().setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY).build();
            sc.startScan(Arrays.asList(f), s, scanCb);
        } catch (SecurityException e) {
            state = "perm_denied";
        } catch (Exception e) {
            state = "error";
        }
    }

    final ScanCallback scanCb = new ScanCallback() {
        @Override public void onScanResult(int t, ScanResult r) {
            try {
                synchronized (BleClient.this) { if (found) return; found = true; }
                stopScan();
                state = "connecting";
                gatt = r.getDevice().connectGatt(ctx, false, gattCb, BluetoothDevice.TRANSPORT_LE);
                if (gatt == null) state = "error";
            } catch (SecurityException e) {
                state = "perm_denied";
            } catch (Exception e) {
                state = "error";
            }
        }
        @Override public void onScanFailed(int e) { state = "scan_failed"; }
    };

    static void refreshCache(BluetoothGatt g) {
        try { g.getClass().getMethod("refresh").invoke(g); } catch (Throwable t) { }
    }

    synchronized void startDiscovery(BluetoothGatt g) {
        if (g == null || g != gatt || discovering) return;
        discovering = true;
        try {
            refreshCache(g);
            if (!g.discoverServices()) { discovering = false; state = "error"; }
        } catch (Exception e) {
            discovering = false; state = "error";
        }
    }

    final BluetoothGattCallback gattCb = new BluetoothGattCallback() {
        @Override public void onConnectionStateChange(final BluetoothGatt g, int status, int ns) {
            try {
                if (ns == BluetoothProfile.STATE_CONNECTED && status == BluetoothGatt.GATT_SUCCESS) {
                    state = "connecting";
                    main.postDelayed(new Runnable() { public void run() {
                        try { if (!g.requestMtu(247)) startDiscovery(g); } catch (Exception e) { startDiscovery(g); }
                    } }, 300);
                    // if the MTU callback never arrives, discover services anyway
                    main.postDelayed(new Runnable() { public void run() { startDiscovery(g); } }, 3000);
                } else {
                    state = "disconnected"; wc = null; writing = false; discovering = false; mtu = 23;
                    try { g.close(); } catch (Exception e) { }
                    if (gatt == g) gatt = null;
                }
            } catch (Exception e) { state = "error"; }
        }
        @Override public void onMtuChanged(BluetoothGatt g, int m, int st) {
            try { if (st == BluetoothGatt.GATT_SUCCESS) mtu = m; } catch (Exception e) { }
            startDiscovery(g);
        }
        @Override public void onServicesDiscovered(BluetoothGatt g, int st) {
            try {
                if (st != BluetoothGatt.GATT_SUCCESS) { state = "no_service"; return; }
                BluetoothGattService s = g.getService(SVC);
                if (s == null) { state = "no_service"; return; }
                BluetoothGattCharacteristic w = s.getCharacteristic(W);
                BluetoothGattCharacteristic nc = s.getCharacteristic(N);
                if (w == null || nc == null) { state = "no_service"; return; }
                BluetoothGattDescriptor d = nc.getDescriptor(CCCD);
                if (d == null) { state = "no_service"; return; }
                wc = w;
                g.setCharacteristicNotification(nc, true);
                d.setValue(BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE);
                if (!g.writeDescriptor(d)) { state = "ready"; pump(); }   // sending still works without notifications
            } catch (Exception e) { state = "error"; }
        }
        @Override public void onDescriptorWrite(BluetoothGatt g, BluetoothGattDescriptor d, int st) {
            try { if (wc != null) { state = "ready"; pump(); } } catch (Exception e) { state = "error"; }
        }
        @Override public void onCharacteristicChanged(BluetoothGatt g, BluetoothGattCharacteristic c) {
            try { byte[] v = c.getValue(); if (v != null) in.add(v.clone()); } catch (Exception e) { }
        }
        @Override public void onCharacteristicWrite(BluetoothGatt g, BluetoothGattCharacteristic c, int st) {
            synchronized (BleClient.this) { writing = false; }
            pump();
        }
    };

    final Runnable pumpAgain = new Runnable() { public void run() { pump(); } };

    public void send(byte[] b) { out.add(b); pump(); }

    synchronized void pump() {
        if (writing || wc == null || gatt == null) return;
        byte[] b = out.poll();
        if (b == null) return;
        try {
            wc.setValue(b);
            wc.setWriteType(BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT);
            writing = true;
            if (!gatt.writeCharacteristic(wc)) { writing = false; out.addFirst(b); main.postDelayed(pumpAgain, 50); }
        } catch (Exception e) {
            writing = false; out.addFirst(b); main.postDelayed(pumpAgain, 200);
        }
    }

    public byte[] poll() { return in.poll(); }
    public int queued() { return out.size(); }
    public int chunkSize() { return Math.max(20, mtu - 3); }
    public String getState() { return state; }

    public void close() {
        stopScan();
        closeGatt();
        state = "idle";
    }
}

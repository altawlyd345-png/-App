package org.bleremote;

import android.bluetooth.*;
import android.bluetooth.le.*;
import android.content.Context;
import android.os.ParcelUuid;
import java.util.*;
import java.util.concurrent.ConcurrentLinkedDeque;

public class BleClient {
    static final UUID SVC = UUID.fromString("12345678-1234-5678-1234-56789abcdef0");
    static final UUID W = UUID.fromString("12345678-1234-5678-1234-56789abcdef1");
    static final UUID N = UUID.fromString("12345678-1234-5678-1234-56789abcdef2");
    static final UUID CCCD = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb");
    Context ctx; BluetoothAdapter ad; BluetoothGatt gatt; BluetoothGattCharacteristic wc;
    volatile String state = "idle"; volatile int mtu = 23; boolean writing = false;
    final ConcurrentLinkedDeque<byte[]> out = new ConcurrentLinkedDeque<>();
    final ConcurrentLinkedDeque<byte[]> in = new ConcurrentLinkedDeque<>();

    public BleClient(Context c) {
        ctx = c;
        ad = ((BluetoothManager) c.getSystemService(Context.BLUETOOTH_SERVICE)).getAdapter();
    }

    public void connect() {
        if (ad == null || !ad.isEnabled()) { state = "bt_off"; return; }
        close();
        try { ad.getBluetoothLeScanner().stopScan(scanCb); } catch (Exception e) {}
        state = "scanning";
        ScanFilter f = new ScanFilter.Builder().setServiceUuid(new ParcelUuid(SVC)).build();
        ScanSettings s = new ScanSettings.Builder().setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY).build();
        ad.getBluetoothLeScanner().startScan(Arrays.asList(f), s, scanCb);
    }

    final ScanCallback scanCb = new ScanCallback() {
        @Override public void onScanResult(int t, ScanResult r) {
            try { ad.getBluetoothLeScanner().stopScan(this); } catch (Exception e) {}
            state = "connecting";
            gatt = r.getDevice().connectGatt(ctx, false, gattCb, BluetoothDevice.TRANSPORT_LE);
        }
        @Override public void onScanFailed(int e) { state = "scan_failed"; }
    };

    final BluetoothGattCallback gattCb = new BluetoothGattCallback() {
        @Override public void onConnectionStateChange(BluetoothGatt g, int st, int ns) {
            if (ns == BluetoothProfile.STATE_CONNECTED) { g.requestMtu(247); }
            else { state = "disconnected"; wc = null; writing = false; g.close(); }
        }
        @Override public void onMtuChanged(BluetoothGatt g, int m, int st) { mtu = m; g.discoverServices(); }
        @Override public void onServicesDiscovered(BluetoothGatt g, int st) {
            BluetoothGattService s = g.getService(SVC);
            if (s == null) { state = "no_service"; return; }
            wc = s.getCharacteristic(W);
            BluetoothGattCharacteristic nc = s.getCharacteristic(N);
            g.setCharacteristicNotification(nc, true);
            BluetoothGattDescriptor d = nc.getDescriptor(CCCD);
            d.setValue(BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE);
            g.writeDescriptor(d);
        }
        @Override public void onDescriptorWrite(BluetoothGatt g, BluetoothGattDescriptor d, int st) { state = "ready"; pump(); }
        @Override public void onCharacteristicChanged(BluetoothGatt g, BluetoothGattCharacteristic c) { in.add(c.getValue()); }
        @Override public void onCharacteristicWrite(BluetoothGatt g, BluetoothGattCharacteristic c, int st) {
            synchronized (BleClient.this) { writing = false; }
            pump();
        }
    };

    public void send(byte[] b) { out.add(b); pump(); }

    synchronized void pump() {
        if (writing || wc == null || gatt == null) return;
        byte[] b = out.poll();
        if (b == null) return;
        wc.setValue(b);
        wc.setWriteType(BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT);
        writing = true;
        if (!gatt.writeCharacteristic(wc)) { writing = false; out.addFirst(b); }
    }

    public byte[] poll() { return in.poll(); }
    public int queued() { return out.size(); }
    public int chunkSize() { return Math.max(20, mtu - 3); }
    public String getState() { return state; }
    public void close() {
        try { if (gatt != null) { gatt.disconnect(); gatt.close(); } } catch (Exception e) {}
        gatt = null; wc = null; out.clear(); writing = false;
    }
}

package org.bleremote;

import android.bluetooth.*;
import android.bluetooth.le.*;
import android.content.Context;
import android.os.ParcelUuid;
import java.util.UUID;
import java.util.concurrent.ConcurrentLinkedDeque;

public class BleServer {
    static final UUID SVC = UUID.fromString("12345678-1234-5678-1234-56789abcdef0");
    static final UUID W = UUID.fromString("12345678-1234-5678-1234-56789abcdef1");
    static final UUID N = UUID.fromString("12345678-1234-5678-1234-56789abcdef2");
    static final UUID CCCD = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb");
    Context ctx; BluetoothManager mgr; BluetoothGattServer server; BluetoothDevice dev;
    BluetoothGattCharacteristic nc;
    volatile String state = "idle"; volatile int mtu = 23;
    final ConcurrentLinkedDeque<byte[]> in = new ConcurrentLinkedDeque<>();

    public BleServer(Context c) { ctx = c; mgr = (BluetoothManager) c.getSystemService(Context.BLUETOOTH_SERVICE); }

    public void start() {
        BluetoothAdapter ad = mgr.getAdapter();
        if (ad == null || !ad.isEnabled()) { state = "bt_off"; return; }
        server = mgr.openGattServer(ctx, cb);
        BluetoothGattService s = new BluetoothGattService(SVC, BluetoothGattService.SERVICE_TYPE_PRIMARY);
        BluetoothGattCharacteristic wc = new BluetoothGattCharacteristic(W,
            BluetoothGattCharacteristic.PROPERTY_WRITE | BluetoothGattCharacteristic.PROPERTY_WRITE_NO_RESPONSE,
            BluetoothGattCharacteristic.PERMISSION_WRITE);
        nc = new BluetoothGattCharacteristic(N, BluetoothGattCharacteristic.PROPERTY_NOTIFY, 0);
        nc.addDescriptor(new BluetoothGattDescriptor(CCCD,
            BluetoothGattDescriptor.PERMISSION_READ | BluetoothGattDescriptor.PERMISSION_WRITE));
        s.addCharacteristic(wc); s.addCharacteristic(nc);
        server.addService(s);
    }

    void advertise() {
        BluetoothLeAdvertiser adv = mgr.getAdapter().getBluetoothLeAdvertiser();
        if (adv == null) { state = "no_advertiser"; return; }
        AdvertiseSettings st = new AdvertiseSettings.Builder()
            .setAdvertiseMode(AdvertiseSettings.ADVERTISE_MODE_LOW_LATENCY).setConnectable(true).setTimeout(0).build();
        AdvertiseData d = new AdvertiseData.Builder().setIncludeDeviceName(false).addServiceUuid(new ParcelUuid(SVC)).build();
        adv.startAdvertising(st, d, new AdvertiseCallback() {
            @Override public void onStartSuccess(AdvertiseSettings s) { if (dev == null) state = "advertising"; }
            @Override public void onStartFailure(int e) { state = "adv_failed_" + e; }
        });
    }

    final BluetoothGattServerCallback cb = new BluetoothGattServerCallback() {
        @Override public void onServiceAdded(int st, BluetoothGattService s) { advertise(); }
        @Override public void onConnectionStateChange(BluetoothDevice d, int st, int ns) {
            if (ns == BluetoothProfile.STATE_CONNECTED) { dev = d; state = "connected"; }
            else { dev = null; state = "advertising"; advertise(); }
        }
        @Override public void onMtuChanged(BluetoothDevice d, int m) { mtu = m; }
        @Override public void onCharacteristicWriteRequest(BluetoothDevice d, int id, BluetoothGattCharacteristic c,
                boolean prep, boolean resp, int off, byte[] v) {
            in.add(v);
            if (resp) server.sendResponse(d, id, BluetoothGatt.GATT_SUCCESS, 0, null);
        }
        @Override public void onDescriptorWriteRequest(BluetoothDevice d, int id, BluetoothGattDescriptor ds,
                boolean prep, boolean resp, int off, byte[] v) {
            if (resp) server.sendResponse(d, id, BluetoothGatt.GATT_SUCCESS, 0, null);
        }
    };

    public void notifyData(byte[] b) {
        if (dev == null || nc == null) return;
        nc.setValue(b);
        server.notifyCharacteristicChanged(dev, nc, false);
    }

    public byte[] poll() { return in.poll(); }
    public int chunkSize() { return Math.max(20, mtu - 3); }
    public String getState() { return state; }
}

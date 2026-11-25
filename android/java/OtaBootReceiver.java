package com.jkurtz.otafwmerger;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

public class OtaBootReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        OtaCheckJobService.syncSchedule(context);
    }
}

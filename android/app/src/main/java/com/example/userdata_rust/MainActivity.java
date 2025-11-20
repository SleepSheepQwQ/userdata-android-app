package com.example.userdata_rust;

import android.app.Activity;
import android.os.Bundle;
import android.view.View;
import android.widget.Button;
import android.widget.TextView;
import android.widget.EditText;
import android.widget.ProgressBar;
import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.appcompat.app.AppCompatActivity;
import android.content.Intent;
import android.net.Uri;
import android.database.Cursor;
import android.provider.DocumentsContract;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;

public class MainActivity extends AppCompatActivity {
    private TextView statusText, logText;
    private ProgressBar progressBar;
    private Button startButton, stopButton, testDbButton, selectDbButton;
    private EditText dbPathEdit, portEdit;
    
    private ActivityResultLauncher<Intent> filePickerLauncher;
    
    static {
        System.loadLibrary("userdata_rust");
    }
    
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);
        
        initViews();
        setupFilePicker();
        updateServerStatus();
    }
    
    private void initViews() {
        statusText = findViewById(R.id.statusText);
        logText = findViewById(R.id.logText);
        progressBar = findViewById(R.id.progressBar);
        
        startButton = findViewById(R.id.startButton);
        stopButton = findViewById(R.id.stopButton);
        testDbButton = findViewById(R.id.testDbButton);
        selectDbButton = findViewById(R.id.selectDbButton);
        
        dbPathEdit = findViewById(R.id.dbPathEdit);
        portEdit = findViewById(R.id.portEdit);
        
        startButton.setOnClickListener(v -> startServer());
        stopButton.setOnClickListener(v -> stopServer());
        testDbButton.setOnClickListener(v -> testDatabase());
        selectDbButton.setOnClickListener(v -> selectDatabaseFile());
    }
    
    private void setupFilePicker() {
        filePickerLauncher = registerForActivityResult(
            new ActivityResultContracts.StartActivityForResult(),
            result -> {
                if (result.getResultCode() == RESULT_OK && result.getData() != null) {
                    Uri uri = result.getData().getData();
                    String path = getPathFromUri(uri);
                    if (path != null) {
                        dbPathEdit.setText(path);
                        appendLog("已选择数据库文件: " + path);
                    }
                }
            }
        );
    }
    
    private void selectDatabaseFile() {
        Intent intent = new Intent(Intent.ACTION_GET_CONTENT);
        intent.setType("application/x-sqlite3");
        intent.addCategory(Intent.CATEGORY_OPENABLE);
        filePickerLauncher.launch(Intent.createChooser(intent, "选择数据库文件"));
    }
    
    private String getPathFromUri(Uri uri) {
        String path = null;
        if ("content".equals(uri.getScheme())) {
            try (Cursor cursor = getContentResolver().query(uri, null, null, null, null)) {
                if (cursor != null && cursor.moveToFirst()) {
                    int index = cursor.getColumnIndex(DocumentsContract.Document.COLUMN_DISPLAY_NAME);
                    if (index >= 0) {
                        String fileName = cursor.getString(index);
                        File destFile = new File(getFilesDir(), fileName);
                        copyFile(uri, destFile);
                        path = destFile.getAbsolutePath();
                    }
                }
            } catch (Exception e) {
                appendLog("获取文件路径失败: " + e.getMessage());
            }
        }
        return path;
    }
    
    private void copyFile(Uri uri, File destFile) {
        try (InputStream in = getContentResolver().openInputStream(uri);
             OutputStream out = new FileOutputStream(destFile)) {
            byte[] buffer = new byte[1024];
            int length;
            while ((length = in.read(buffer)) > 0) {
                out.write(buffer, 0, length);
            }
        } catch (Exception e) {
            appendLog("文件复制失败: " + e.getMessage());
        }
    }
    
    private void startServer() {
        String config = String.format(
            "{"db_path":"%s","port":%s}",
            dbPathEdit.getText().toString(),
            portEdit.getText().toString()
        );
        
        progressBar.setVisibility(View.VISIBLE);
        new Thread(() -> {
            String result = startServer(config);
            runOnUiThread(() -> {
                progressBar.setVisibility(View.GONE);
                appendLog(result);
                updateServerStatus();
            });
        }).start();
    }
    
    private void stopServer() {
        new Thread(() -> {
            String result = stopServer();
            runOnUiThread(() -> {
                appendLog(result);
                updateServerStatus();
            });
        }).start();
    }
    
    private void testDatabase() {
        String dbPath = dbPathEdit.getText().toString();
        progressBar.setVisibility(View.VISIBLE);
        
        new Thread(() -> {
            String result = testDatabase(dbPath);
            runOnUiThread(() -> {
                progressBar.setVisibility(View.GONE);
                appendLog(result);
            });
        }).start();
    }
    
    private void updateServerStatus() {
        new Thread(() -> {
            String status = getServerStatus();
            runOnUiThread(() -> {
                statusText.setText("服务状态: " + status);
                startButton.setEnabled("stopped".equals(status));
                stopButton.setEnabled("running".equals(status));
            });
        }).start();
    }
    
    private void appendLog(String message) {
        runOnUiThread(() -> {
            String timestamp = new java.text.SimpleDateFormat("HH:mm:ss").format(new java.util.Date());
            logText.setText(timestamp + ": " + message + "\n" + logText.getText());
        });
    }
    
    // JNI方法
    public native String startServer(String configJson);
    public native String stopServer();
    public native String getServerStatus();
    public native String testDatabase(String dbPath);
}

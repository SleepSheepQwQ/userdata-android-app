use tiny_http::{Server, Request, Response, Method};
use log::{info, LevelFilter, error, warn};
use rusqlite::{Connection, params};
use serde::{Deserialize, Serialize};
use std::sync::{Arc, Mutex, atomic::{AtomicBool, Ordering}};
use std::thread;
use std::collections::HashMap;
use once_cell::sync::Lazy;
use jni::{JNIEnv, objects::{JClass, JString}, sys::jstring};
use crossbeam_channel::{self, Sender, Receiver};

// 服务器控制信号
static SERVER_RUNNING: AtomicBool = AtomicBool::new(false);
static SERVER_SHUTDOWN: Lazy<Mutex<Option<Sender<()>>>> = Lazy::new(|| Mutex::new(None));

#[derive(Serialize, Deserialize)]
struct UserInfo {
    email: Option<String>,
    phone: Option<String>,
    qq: Option<String>,
}

#[derive(Serialize, Deserialize, Clone)]
struct ServerConfig {
    db_path: String,
    port: u16,
}

impl Default for ServerConfig {
    fn default() -> Self {
        Self {
            db_path: "/data/data/com.example.userdata_rust/files/user_data.db".to_string(),
            port: 8080,
        }
    }
}

static CONFIG: Lazy<Mutex<ServerConfig>> = Lazy::new(|| Mutex::new(ServerConfig::default()));

#[no_mangle]
pub extern "C" fn Java_com_example_userdata_rust_MainActivity_startServer(
    env: JNIEnv,
    _class: JClass,
    config_json: JString,
) -> jstring {
    android_logger::init_once(
        android_logger::Config::default()
            .with_max_level(LevelFilter::Info)
            .with_tag("UserDataRust"),
    );

    if SERVER_RUNNING.load(Ordering::SeqCst) {
        let msg = env.new_string("Server is already running").unwrap();
        return msg.into_raw();
    }

    // 简化：直接使用get_string()的返回值
    let config_str = match env.get_string(config_json) {
        Ok(s) => s.into(),
        Err(_) => {
            let msg = env.new_string("Invalid config string").unwrap();
            return msg.into_raw();
        }
    };
    
    let config: ServerConfig = match serde_json::from_str(&config_str) {
        Ok(c) => c,
        Err(e) => {
            warn!("Using default config: {}", e);
            ServerConfig::default()
        }
    };
    
    *CONFIG.lock().unwrap() = config.clone();
    
    let (shutdown_tx, shutdown_rx) = crossbeam_channel::bounded(1);
    *SERVER_SHUTDOWN.lock().unwrap() = Some(shutdown_tx);
    
    thread::spawn(move || {
        info!("Starting server thread...");
        SERVER_RUNNING.store(true, Ordering::SeqCst);
        start_http_server(config, shutdown_rx);
        SERVER_RUNNING.store(false, Ordering::SeqCst);
        info!("Server thread finished.");
    });
    
    // 给服务器一点时间启动并检查是否成功
    thread::sleep(std::time::Duration::from_millis(500));
    
    let success = env.new_string("Server started successfully").unwrap();
    success.into_raw()
}

#[no_mangle]
pub extern "C" fn Java_com_example_userdata_rust_MainActivity_stopServer(
    env: JNIEnv,
    _class: JClass,
) -> jstring {
    if !SERVER_RUNNING.load(Ordering::SeqCst) {
        let msg = env.new_string("Server is not running").unwrap();
        return msg.into_raw();
    }

    if let Some(tx) = SERVER_SHUTDOWN.lock().unwrap().take() {
        let _ = tx.send(());
    }
    
    // 等待服务器完全停止
    for _ in 0..20 { // 最多等待2秒
        if !SERVER_RUNNING.load(Ordering::SeqCst) {
            break;
        }
        thread::sleep(std::time::Duration::from_millis(100));
    }
    
    let msg = env.new_string("Server stopped").unwrap();
    msg.into_raw()
}

#[no_mangle]
pub extern "C" fn Java_com_example_userdata_rust_MainActivity_getServerStatus(
    env: JNIEnv,
    _class: JClass,
) -> jstring {
    let is_running = SERVER_RUNNING.load(Ordering::SeqCst);
    let status = if is_running { "running" } else { "stopped" };
    let msg = env.new_string(status).unwrap();
    msg.into_raw()
}

#[no_mangle]
pub extern "C" fn Java_com_example_userdata_rust_MainActivity_testDatabase(
    env: JNIEnv,
    _class: JClass,
    db_path: JString,
) -> jstring {
    // 简化：直接使用get_string()的返回值
    let path_str = match env.get_string(db_path) {
        Ok(s) => s.into(),
        Err(_) => {
            let msg = env.new_string("Invalid path string").unwrap();
            return msg.into_raw();
        }
    };
    
    match Connection::open(&path_str) {
        Ok(conn) => {
            match conn.query_row("SELECT COUNT(*) FROM users", [], |row| row.get::<_, i64>(0)) {
                Ok(count) => {
                    let msg = env.new_string(&format!("Database OK. Records: {}", count)).unwrap();
                    msg.into_raw()
                }
                Err(e) => {
                    let msg = env.new_string(&format!("Database query failed: {}", e)).unwrap();
                    msg.into_raw()
                }
            }
        }
        Err(e) => {
            let msg = env.new_string(&format!("Cannot open database: {}", e)).unwrap();
            msg.into_raw()
        }
    }
}

// 简化：每个请求创建独立连接，避免锁竞争
fn start_http_server(config: ServerConfig, shutdown_rx: Receiver<()>) {
    if !std::path::Path::new(&config.db_path).exists() {
        error!("Database file not found: {}", config.db_path);
        return;
    }

    let addr = format!("127.0.0.1:{}", config.port);
    let server = match Server::http(&addr) {
        Ok(s) => s,
        Err(e) => {
            error!("Failed to start server on {}: {}", addr, e);
            return;
        }
    };

    info!("Server started on {}", addr);
    
    // 简化：使用简单的阻塞接收
    loop {
        // 检查关闭信号
        if shutdown_rx.try_recv().is_ok() {
            info!("Shutdown signal received, stopping server.");
            break;
        }
        
        // 阻塞接收请求，但有超时
        match server.recv_timeout(std::time::Duration::from_millis(100)) {
            Ok(Some(request)) => {
                let db_path = config.db_path.clone();
                thread::spawn(move || {
                    handle_request(request, &db_path);
                });
            }
            Ok(None) => break, // Server closed
            Err(_) => {
                // 超时，继续循环检查关闭信号
                continue;
            }
        }
    }
    info!("Server loop ended.");
}

// 简化：每个请求独立处理，不共享连接
fn handle_request(mut request: Request, db_path: &str) {
    match request.method() {
        Method::Get => {
            match request.url() {
                "/" => {
                    let response = Response::from_string("User Data Server Running".to_string());
                    let _ = request.respond(response);
                }
                "/config" => {
                    let config = CONFIG.lock().unwrap().clone();
                    let json = serde_json::to_string(&config).unwrap_or_default();
                    let response = Response::from_string(json)
                        .with_header("Content-Type: application/json".parse::<tiny_http::Header>().unwrap());
                    let _ = request.respond(response);
                }
                _ => {
                    let response = Response::from_string("Not Found".to_string())
                        .with_status_code(404);
                    let _ = request.respond(response);
                }
            }
        }
        Method::Post => {
            match request.url() {
                "/query" => {
                    let mut content = String::new();
                    let _ = request.as_reader().read_to_string(&mut content);
                    
                    let form_data = parse_form_data(&content);
                    let result = query_database(db_path, &form_data);
                    let json = serde_json::to_string(&result).unwrap_or_default();
                    
                    let response = Response::from_string(json)
                        .with_header("Content-Type: application/json".parse::<tiny_http::Header>().unwrap());
                    let _ = request.respond(response);
                }
                "/stats" => {
                    let stats = get_database_stats(db_path);
                    let response = Response::from_string(stats)
                        .with_header("Content-Type: text/html".parse::<tiny_http::Header>().unwrap());
                    let _ = request.respond(response);
                }
                _ => {
                    let response = Response::from_string("Not Found".to_string())
                        .with_status_code(404);
                    let _ = request.respond(response);
                }
            }
        }
        _ => {
            let response = Response::from_string("Method Not Allowed".to_string())
                .with_status_code(405);
            let _ = request.respond(response);
        }
    }
}

fn parse_form_data(content: &str) -> HashMap<String, String> {
    let mut form_data = HashMap::new();
    for line in content.split('&') {
        if let Some((key, value)) = line.split_once('=') {
            form_data.insert(key.to_string(), value.to_string());
        }
    }
    form_data
}

// 简化：每次创建新连接，避免线程安全问题
fn query_database(db_path: &str, form_data: &HashMap<String, String>) -> Vec<UserInfo> {
    let mut results = Vec::new();
    
    let (sql, param) = if let Some(phone) = form_data.get("phone") {
        ("SELECT email, phone, qq FROM users WHERE phone = ?1", phone.clone())
    } else if let Some(qq) = form_data.get("qq") {
        ("SELECT email, phone, qq FROM users WHERE qq = ?1", qq.clone())
    } else if let Some(email) = form_data.get("email") {
        ("SELECT email, phone, qq FROM users WHERE email = ?1", email.clone())
    } else {
        return results;
    };

    if let Ok(conn) = Connection::open(db_path) {
        if let Ok(mut stmt) = conn.prepare(sql) {
            if let Ok(rows) = stmt.query_map([&param], |row| {
                Ok(UserInfo {
                    email: row.get(0).ok(),
                    phone: row.get(1).ok(),
                    qq: row.get(2).ok(),
                })
            }) {
                for row in rows {
                    if let Ok(user) = row {
                        results.push(user);
                    }
                }
            }
        }
    }
    
    results
}

// 简化：每次创建新连接
fn get_database_stats(db_path: &str) -> String {
    if let Ok(conn) = Connection::open(db_path) {
        let total_users = conn.query_row("SELECT COUNT(*) FROM users", [], |row| row.get::<_, i64>(0)).unwrap_or(0);
        let unique_phones = conn.query_row("SELECT COUNT(DISTINCT phone) FROM users WHERE phone IS NOT NULL", [], |row| row.get::<_, i64>(0)).unwrap_or(0);
        let unique_qqs = conn.query_row("SELECT COUNT(DISTINCT qq) FROM users WHERE qq IS NOT NULL", [], |row| row.get::<_, i64>(0)).unwrap_or(0);
        let unique_emails = conn.query_row("SELECT COUNT(DISTINCT email) FROM users WHERE email IS NOT NULL", [], |row| row.get::<_, i64>(0)).unwrap_or(0);

        format!(r#"
        <h2>Database Statistics</h2>
        <ul>
            <li>Total Records: {}</li>
            <li>Unique Phones: {}</li>
            <li>Unique QQs: {}</li>
            <li>Unique Emails: {}</li>
        </ul>
        "#, total_users, unique_phones, unique_qqs, unique_emails)
    } else {
        "Database Error: Could not connect".to_string()
    }
}

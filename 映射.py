#!/usr/bin/env python3
import os
import json
import time
import hashlib
import threading
import signal
from pathlib import Path
from datetime import datetime
import chardet
import mimetypes
import sys
import tty
import termios
import select
import re

class PauseController:
    def __init__(self):
        self.paused = False
        self.lock = threading.Lock()
        
    def toggle_pause(self):
        with self.lock:
            self.paused = not self.paused
            return self.paused
    
    def is_paused(self):
        with self.lock:
            return self.paused

class RealTimeDirectoryTree:
    def __init__(self, source_dir, target_dir):
        self.source_dir = Path(source_dir).resolve()
        self.target_dir = Path(target_dir).resolve()
        self.tree_data = {}
        self.file_status = {}
        self.last_update = time.time()
        self.pause_controller = PauseController()
        self.last_display_lines = []
        
    def _is_hash_filename(self, name):
        """检测是否为哈希值文件名（更宽松的检测）"""
        # 移除扩展名
        base_name = name.split('.')[0]
        
        # 检查是否为较长的十六进制字符串（20位或以上）
        # 这能捕获各种长度的哈希值
        if len(base_name) >= 20 and re.match(r'^[a-fA-F0-9]+$', base_name):
            return True
        
        return False
    
    def _format_filename(self, name):
        """格式化文件名显示"""
        # 检查是否为哈希值文件
        if self._is_hash_filename(name):
            base_name = name.split('.')[0]
            ext = name.split('.')[1] if '.' in name and len(name.split('.')) > 1 else ''
            
            # 显示为 [hash+前三位]
            if len(base_name) >= 3:
                hash_display = f"[{base_name[:3]}]"
                if ext:
                    return f"{hash_display}.{ext}"
                return hash_display
        
        # 非哈希文件：完整显示
        return name
    
    def _format_size(self, size_bytes):
        if size_bytes == 0:
            return "0 B"
        size_names = ["B", "KB", "MB", "GB"]
        i = 0
        while size_bytes >= 1024 and i < len(size_names) - 1:
            size_bytes /= 1024.0
            i += 1
        return f"{size_bytes:.1f} {size_names[i]}"
    
    def _get_tree_line(self, path, depth=0, is_last=False, prefix=""):
        name = path.name if path.name else path.as_posix()
        
        # 格式化文件名显示
        display_name = self._format_filename(name)
        
        node_info = self.tree_data.get(str(path), {'type': 'file', 'size': 0, 'status': 'normal', 'is_text': True})
        
        status_icons = {
            'normal': "  ",
            'new': "🆕",
            'modified': "✏️ ",
            'deleted': "🗑️ ",
            'syncing': "🔄",
            'error': "❌"
        }
        
        status_icon = status_icons.get(node_info.get('status', 'normal'), "  ")
        
        if node_info.get('type') == 'dir':
            type_icon = "📁"
            size_info = f"[{self._format_size(node_info.get('size', 0))}]"
        else:
            if node_info.get('is_text', True):
                type_icon = "📄"
                size_info = f"[{self._format_size(node_info.get('size', 0))}]"
            else:
                type_icon = "🗃️"
                size_info = f"[{display_name}]"  # 非文本文件显示格式化后的文件名
        
        if depth == 0:
            connector = ""
        elif is_last:
            connector = prefix + "└─ "
        else:
            connector = prefix + "├─ "
        
        return f"{connector}{status_icon}{type_icon} {display_name} {size_info}"
    
    def _build_tree_display(self, path=None, depth=0, prefix="", is_last=True):
        if path is None:
            path = self.source_dir
        
        lines = []
        lines.append(self._get_tree_line(path, depth, is_last, prefix))
        
        if path.is_dir():
            children = []
            try:
                for item in sorted(path.iterdir(), key=lambda x: (x.is_file(), x.name.lower())):
                    children.append(item)
            except:
                pass
            
            for i, child in enumerate(children):
                child_is_last = (i == len(children) - 1)
                child_prefix = prefix + ("   " if is_last else "│  ")
                
                child_lines = self._build_tree_display(
                    child, depth + 1, child_prefix, child_is_last
                )
                lines.extend(child_lines)
        
        return lines
    
    def update_tree(self, file_changes):
        current_time = time.time()
        
        for change_type, file_path in file_changes:
            path_str = str(file_path)
            
            if change_type == 'new':
                self.tree_data[path_str] = {
                    'type': 'file',
                    'size': file_path.stat().st_size if file_path.exists() else 0,
                    'status': 'new',
                    'is_text': self._is_text_file(file_path)
                }
            elif change_type == 'modified':
                if path_str in self.tree_data:
                    self.tree_data[path_str]['status'] = 'modified'
                    self.tree_data[path_str]['size'] = file_path.stat().st_size
            elif change_type == 'deleted':
                if path_str in self.tree_data:
                    self.tree_data[path_str]['status'] = 'deleted'
        
        self._update_directory_sizes()
        
        if current_time - self.last_update > 5:
            for path_str in self.tree_data:
                if self.tree_data[path_str]['status'] in ['new', 'modified']:
                    self.tree_data[path_str]['status'] = 'normal'
            self.last_update = current_time
    
    def _is_text_file(self, file_path):
        try:
            text_extensions = {
                '.txt', '.py', '.js', '.html', '.css', '.json', '.xml', 'md',
                '.yml', '.yaml', '.ini', '.cfg', '.conf', '.log', '.csv',
                '.sh', '.bat', '.cmd', '.ps1', '.sql', '.r', '.m', '.c',
                '.cpp', '.h', '.hpp', '.java', '.kt', '.swift', '.go', '.rs'
            }
            
            if file_path.suffix.lower() in text_extensions:
                return True
            
            mime_type, _ = mimetypes.guess_type(str(file_path))
            if mime_type and mime_type.startswith('text/'):
                return True
            
            with open(file_path, 'rb') as f:
                sample = f.read(1024)
                if b'\x00' in sample:
                    return False
                
                printable = sum(1 for b in sample if 32 <= b <= 126 or b in [9, 10, 13])
                if printable / len(sample) > 0.8:
                    return True
            
            return False
        except:
            return False
    
    def _update_directory_sizes(self):
        def calculate_dir_size(dir_path):
            total_size = 0
            try:
                for item in dir_path.rglob('*'):
                    if item.is_file():
                        total_size += item.stat().st_size
            except:
                pass
            return total_size
        
        for path_str, info in self.tree_data.items():
            path = Path(path_str)
            if path.is_dir() and path.exists():
                info['size'] = calculate_dir_size(path)
    
    def display_tree(self, status_info):
        # 构建显示内容
        pause_status = "⏸️ 已暂停" if self.pause_controller.is_paused() else "▶️ 运行中"
        
        lines = []
        lines.append("🌳 实时文件监控 - 完整目录树")
        lines.append("=" * 80)
        lines.append(f"📁 源目录: {self.source_dir}")
        lines.append(f"📂 目标目录: {self.target_dir}")
        lines.append(f"⏰ 更新时间: {datetime.now().strftime('%H:%M:%S')}")
        lines.append(f"🎮 状态: {pause_status} | 按ESC暂停/继续 | 按q退出")
        lines.append(f"📊 {status_info}")
        lines.append("=" * 80)
        
        tree_lines = self._build_tree_display()
        lines.extend(tree_lines)
        
        lines.append(f"\n总计: {len(tree_lines)} 个项目")
        if self.pause_controller.is_paused():
            lines.append("\n⏸️ 已暂停 - 现在可以复制内容了！按ESC继续监控")
        
        # 保存显示内容
        self.last_display_lines = lines
        
        # 清屏并显示
        os.system('clear' if os.name == 'posix' else 'cls')
        for line in lines:
            print(line)
    
    def show_paused_screen(self):
        """显示暂停时的静态界面（不重新构建树）"""
        if not self.last_display_lines:
            return
        
        # 更新状态行
        for i, line in enumerate(self.last_display_lines):
            if "🎮 状态:" in line:
                self.last_display_lines[i] = "🎮 状态: ⏸️ 已暂停 | 按ESC继续 | 按q退出"
            elif "⏸️ 已暂停 - 现在可以复制内容了！" not in line and i == len(self.last_display_lines) - 1:
                self.last_display_lines.append("\n⏸️ 已暂停 - 现在可以复制内容了！按ESC继续监控")
                break
        
        # 清屏并显示保存的内容
        os.system('clear' if os.name == 'posix' else 'cls')
        for line in self.last_display_lines:
            print(line)

class KeyboardListener:
    def __init__(self, pause_controller):
        self.pause_controller = pause_controller
        self.running = False
        self.old_settings = None
        self.exit_requested = False
        
        # 注册信号处理器
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """优雅处理终止信号"""
        print("\n\n收到退出信号，正在清理...")
        self.exit_requested = True
        self.running = False
        # 立即恢复终端设置
        if self.old_settings:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self.old_settings)
    
    def start(self):
        self.running = True
        self.exit_requested = False
        thread = threading.Thread(target=self._listen, daemon=True)
        thread.start()
    
    def _listen(self):
        self.old_settings = termios.tcgetattr(sys.stdin)
        
        try:
            tty.setcbreak(sys.stdin.fileno())
            
            while self.running and not self.exit_requested:
                if select.select([sys.stdin], [], [], 0) == ([sys.stdin], [], []):
                    try:
                        key = sys.stdin.read(1)
                        
                        if key == '\x1b':  # ESC
                            self.pause_controller.toggle_pause()
                        elif key == 'q':
                            # 正常退出，让finally执行
                            break
                        elif key == '\x03':  # Ctrl+C
                            # 不直接退出，让信号处理器处理
                            break
                    except:
                        pass
                
                time.sleep(0.1)
        finally:
            # 确保恢复终端设置
            if self.old_settings:
                try:
                    termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self.old_settings)
                except:
                    pass
            # 通知主程序退出
            self.exit_requested = True
    
    def stop(self):
        self.running = False
        self.exit_requested = True
        # 立即恢复终端设置
        if self.old_settings:
            try:
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self.old_settings)
            except:
                pass
    
    def should_exit(self):
        return self.exit_requested

class EnhancedFileMonitor:
    def __init__(self, source_dir, target_dir, excluded_dirs):
        self.source_dir = Path(source_dir).resolve()
        self.target_dir = Path(target_dir).resolve()
        self.excluded_dirs = set(Path(d).resolve() for d in excluded_dirs)
        self.file_states = {}
        self.running = False
        self.poll_interval = 2.0
        self.tree = RealTimeDirectoryTree(source_dir, target_dir)
        self.file_changes = []
        self.stats = {
            'total_files': 0,
            'text_files': 0,
            'binary_files': 0,
            'synced_files': 0,
            'errors': 0,
            'last_sync': None
        }
        self.keyboard_listener = KeyboardListener(self.tree.pause_controller)
        self.last_pause_state = False
        
    def _is_text_file(self, file_path):
        return self.tree._is_text_file(file_path)
    
    def _should_process(self, path):
        try:
            path = Path(path).resolve()
            
            for excluded in self.excluded_dirs:
                if str(path).startswith(str(excluded)):
                    return False
            
            return path.is_file()
        except:
            return False
    
    def _copy_file_with_encoding(self, src_path, target_path):
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            
            if self._is_text_file(src_path):
                with open(src_path, 'rb') as f:
                    raw_data = f.read()
                
                if not raw_data:
                    with open(target_path, 'w', encoding='utf-8') as f:
                        f.write('')
                    return True
                
                detected = chardet.detect(raw_data)
                encoding = detected.get('encoding', 'utf-8')
                confidence = detected.get('confidence', 0)
                
                if confidence < 0.7:
                    for enc in ['utf-8', 'gbk', 'gb2312', 'big5', 'latin1']:
                        try:
                            raw_data.decode(enc)
                            encoding = enc
                            break
                        except UnicodeDecodeError:
                            continue
                
                content = raw_data.decode(encoding, errors='replace')
                with open(target_path, 'w', encoding='utf-8') as f:
                    f.write(content)
            else:
                import shutil
                shutil.copy2(src_path, target_path)
            
            return True
            
        except Exception as e:
            print(f"复制失败 {src_path.name}: {e}")
            return False
    
    def _scan_directory(self):
        files = []
        dirs = []
        try:
            for root, dirnames, filenames in os.walk(self.source_dir):
                for dirname in dirnames:
                    dir_path = Path(root) / dirname
                    dirs.append(dir_path)
                    
                for filename in filenames:
                    file_path = Path(root) / filename
                    if self._should_process(file_path):
                        files.append(file_path)
        except Exception as e:
            print(f"扫描失败: {e}")
        
        return files, dirs
    
    def _get_file_state(self, file_path):
        try:
            stat = file_path.stat()
            return (stat.st_mtime, stat.st_size)
        except:
            return None
    
    def _check_file_changes(self):
        current_files, current_dirs = self._scan_directory()
        current_files_set = set(current_files)
        previous_files_set = set(self.file_states.keys())
        
        for dir_path in current_dirs:
            self.tree.tree_data[str(dir_path)] = {
                'type': 'dir',
                'size': 0,
                'status': 'normal'
            }
        
        text_count = 0
        binary_count = 0
        for file_path in current_files:
            is_text = self._is_text_file(file_path)
            if is_text:
                text_count += 1
            else:
                binary_count += 1
                
            self.tree.tree_data[str(file_path)] = {
                'type': 'file',
                'size': file_path.stat().st_size,
                'status': 'normal',
                'is_text': is_text
            }
        
        new_files = current_files_set - previous_files_set
        for file_path in new_files:
            state = self._get_file_state(file_path)
            if state:
                self.file_states[file_path] = state
                target_path = self._get_target_path(file_path)
                if self._copy_file_with_encoding(file_path, target_path):
                    self.file_changes.append(('new', file_path))
                    self.stats['synced_files'] += 1
        
        deleted_files = previous_files_set - current_files_set
        for file_path in deleted_files:
            del self.file_states[file_path]
            target_path = self._get_target_path(file_path)
            if target_path.exists():
                target_path.unlink()
            self.file_changes.append(('deleted', file_path))
            if str(file_path) in self.tree.tree_data:
                del self.tree.tree_data[str(file_path)]
        
        for file_path in current_files:
            current_state = self._get_file_state(file_path)
            if current_state and current_state != self.file_states.get(file_path):
                self.file_states[file_path] = current_state
                target_path = self._get_target_path(file_path)
                if self._copy_file_with_encoding(file_path, target_path):
                    self.file_changes.append(('modified', file_path))
                    self.stats['synced_files'] += 1
        
        self.stats['total_files'] = len(current_files)
        self.stats['text_files'] = text_count
        self.stats['binary_files'] = binary_count
        self.stats['last_sync'] = datetime.now().strftime('%H:%M:%S')
        
        self.tree.update_tree(self.file_changes)
        
        if len(self.file_changes) > 10:
            self.file_changes = self.file_changes[-10:]
    
    def _get_target_path(self, src_path):
        try:
            rel_path = src_path.relative_to(self.source_dir)
        except ValueError:
            rel_path = src_path.name
        
        if self._is_text_file(src_path):
            return self.target_dir / rel_path.with_suffix('.txt')
        else:
            return self.target_dir / rel_path
    
    def _display_loop(self):
        while self.running and not self.keyboard_listener.should_exit():
            current_pause_state = self.tree.pause_controller.is_paused()
            
            # 检查暂停状态变化
            if current_pause_state != self.last_pause_state:
                self.last_pause_state = current_pause_state
                if current_pause_state:
                    # 刚暂停，显示静态界面
                    self.tree.show_paused_screen()
                    time.sleep(1)
                    continue
            
            # 如果暂停了，就不刷新界面
            if current_pause_state:
                time.sleep(1)
                continue
            
            # 检查是否需要退出
            if self.keyboard_listener.should_exit():
                break
            
            # 正常运行时才刷新
            recent_changes = [f"{change[0]}: {change[1].name}" for change in self.file_changes[-3:]]
            status_text = f"总计: {self.stats['total_files']} | 文本: {self.stats['text_files']} | 二进制: {self.stats['binary_files']} | 同步: {self.stats['synced_files']} | "
            if recent_changes:
                status_text += f"最近: {', '.join(recent_changes)}"
            else:
                status_text += "无变化"
            
            self.tree.display_tree(status_text)
            time.sleep(self.poll_interval)
    
    def _monitor_loop(self):
        while self.running and not self.keyboard_listener.should_exit():
            # 如果暂停了，就不检查文件变化
            if not self.tree.pause_controller.is_paused():
                start_time = time.time()
                self._check_file_changes()
                elapsed = time.time() - start_time
                sleep_time = max(0, self.poll_interval - elapsed)
                time.sleep(sleep_time)
            else:
                time.sleep(1)
    
    def start_monitoring(self):
        self.running = True
        
        print("初始化...")
        files, dirs = self._scan_directory()
        
        for dir_path in dirs:
            self.tree.tree_data[str(dir_path)] = {
                'type': 'dir',
                'size': 0,
                'status': 'normal'
            }
        
        text_count = 0
        binary_count = 0
        for file_path in files:
            is_text = self._is_text_file(file_path)
            if is_text:
                text_count += 1
            else:
                binary_count += 1
                
            self.file_states[file_path] = self._get_file_state(file_path)
            self.tree.tree_data[str(file_path)] = {
                'type': 'file',
                'size': file_path.stat().st_size,
                'status': 'normal',
                'is_text': is_text
            }
            
            target_path = self._get_target_path(file_path)
            self._copy_file_with_encoding(file_path, target_path)
        
        self.stats['total_files'] = len(files)
        self.stats['text_files'] = text_count
        self.stats['binary_files'] = binary_count
        self.stats['synced_files'] = len(files)
        
        self.keyboard_listener.start()
        
        display_thread = threading.Thread(target=self._display_loop, daemon=True)
        monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        
        display_thread.start()
        monitor_thread.start()
        
        try:
            while self.running and not self.keyboard_listener.should_exit():
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop_monitoring()
    
    def stop_monitoring(self):
        self.running = False
        self.keyboard_listener.stop()
        print("\n监控已停止")

def get_directory_input(prompt):
    while True:
        path_input = input(f"{prompt}: ").strip()
        if not path_input:
            print("请输入路径")
            continue
            
        path = Path(path_input).expanduser().resolve()
        
        if not path.exists():
            create = input(f"目录不存在，创建吗？(y/n): ").strip().lower()
            if create == 'y':
                try:
                    path.mkdir(parents=True, exist_ok=True)
                except:
                    print("创建失败")
                    continue
            else:
                continue
        
        if not path.is_dir():
            print("不是目录")
            continue
            
        return path

def load_config(source_dir):
    config_file = source_dir / '.monitor_config.json'
    excluded_dirs = set()
    
    if config_file.exists():
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
                excluded_dirs = set(config.get('excluded_dirs', []))
        except:
            pass
    
    return excluded_dirs, config_file

def configure_excluded_dirs(source_dir):
    excluded_dirs = set()
    
    print("\n排除目录设置:")
    print("输入要排除的目录名，直接回车结束")
    
    while True:
        dir_input = input("排除目录: ").strip()
        if not dir_input:
            break
        excluded_dirs.add(dir_input)
    
    config_file = source_dir / '.monitor_config.json'
    config = {'excluded_dirs': list(excluded_dirs)}
    
    try:
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        print("配置已保存")
    except:
        print("保存配置失败")
    
    return excluded_dirs

def main():
    print("实时文件监控 - ESC键暂停/继续")
    print("=" * 50)
    
    source_dir = get_directory_input("源目录")
    target_dir = get_directory_input("目标目录")
    
    excluded_dirs, config_file = load_config(source_dir)
    
    if not config_file.exists():
        print("首次运行，需要配置排除目录")
        excluded_dirs = configure_excluded_dirs(source_dir)
    else:
        reconfig = input("重新配置排除目录？(y/n): ").strip().lower()
        if reconfig == 'y':
            excluded_dirs = configure_excluded_dirs(source_dir)
    
    print("\n检查间隔设置:")
    print("1. 1秒 (最快)")
    print("2. 2秒 (推荐)")
    print("3. 3秒 (平衡)")
    print("4. 5秒 (省电)")
    
    poll_interval = 2.0
    while True:
        choice = input("请选择 (1-4，默认2): ").strip()
        if not choice:
            choice = "2"
        
        if choice == "1":
            poll_interval = 1.0
            break
        elif choice == "2":
            poll_interval = 2.0
            break
        elif choice == "3":
            poll_interval = 3.0
            break
        elif choice == "4":
            poll_interval = 5.0
            break
        else:
            print("请输入 1-4")
    
    monitor = EnhancedFileMonitor(source_dir, target_dir, excluded_dirs)
    monitor.poll_interval = poll_interval
    monitor.start_monitoring()

if __name__ == '__main__':
    main()

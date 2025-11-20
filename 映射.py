#!/usr/bin/env python3
import os
import json
import time
import hashlib
from pathlib import Path
from datetime import datetime
import chardet
import mimetypes

class MobileFriendlyFileMonitor:
    def __init__(self, source_dir, target_dir, excluded_dirs):
        self.source_dir = Path(source_dir).resolve()
        self.target_dir = Path(target_dir).resolve()
        self.excluded_dirs = set(Path(d).resolve() for d in excluded_dirs)
        self.file_states = {}
        self.running = False
        self.poll_interval = 2.0  # 合理的默认值
        
    def _get_file_hash(self, file_path, sample_size=8192):
        try:
            with open(file_path, 'rb') as f:
                data = f.read(sample_size)
                f.seek(-min(sample_size, os.path.getsize(file_path)), 2)
                data += f.read(sample_size)
            return hashlib.md5(data).hexdigest()
        except:
            return None
    
    def _is_text_file(self, file_path):
        try:
            text_extensions = {
                '.txt', '.py', '.js', '.html', '.css', '.json', '.xml', '.md',
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
    
    def _should_process(self, path):
        try:
            path = Path(path).resolve()
            
            for excluded in self.excluded_dirs:
                if str(path).startswith(str(excluded)):
                    return False
            
            return path.is_file() and self._is_text_file(path)
        except:
            return False
    
    def _copy_file_with_encoding(self, src_path, target_path):
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            
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
            
            return True
            
        except Exception as e:
            print(f"复制失败 {src_path.name}: {e}")
            return False
    
    def _scan_directory(self):
        files = []
        try:
            for root, _, filenames in os.walk(self.source_dir):
                for filename in filenames:
                    file_path = Path(root) / filename
                    if self._should_process(file_path):
                        files.append(file_path)
        except Exception as e:
            print(f"扫描失败: {e}")
        return files
    
    def _get_file_state(self, file_path):
        try:
            stat = file_path.stat()
            return (stat.st_mtime, stat.st_size, self._get_file_hash(file_path))
        except:
            return None
    
    def _check_file_changes(self):
        current_files = self._scan_directory()
        current_files_set = set(current_files)
        previous_files_set = set(self.file_states.keys())
        
        new_files = current_files_set - previous_files_set
        for file_path in new_files:
            state = self._get_file_state(file_path)
            if state:
                self.file_states[file_path] = state
                target_path = self._get_target_path(file_path)
                if self._copy_file_with_encoding(file_path, target_path):
                    print(f"新文件: {file_path.name}")
        
        deleted_files = previous_files_set - current_files_set
        for file_path in deleted_files:
            del self.file_states[file_path]
            target_path = self._get_target_path(file_path)
            if target_path.exists():
                target_path.unlink()
                print(f"删除: {file_path.name}")
        
        for file_path in current_files:
            current_state = self._get_file_state(file_path)
            if current_state and current_state != self.file_states.get(file_path):
                self.file_states[file_path] = current_state
                target_path = self._get_target_path(file_path)
                if self._copy_file_with_encoding(file_path, target_path):
                    print(f"更新: {file_path.name}")
    
    def _get_target_path(self, src_path):
        try:
            rel_path = src_path.relative_to(self.source_dir)
        except ValueError:
            rel_path = src_path.name
        return self.target_dir / rel_path.with_suffix('.txt')
    
    def _initial_sync(self):
        print("开始初始同步...")
        files = self._scan_directory()
        synced_count = 0
        
        for file_path in files:
            state = self._get_file_state(file_path)
            if state:
                self.file_states[file_path] = state
                target_path = self._get_target_path(file_path)
                if self._copy_file_with_encoding(file_path, target_path):
                    synced_count += 1
        
        print(f"初始同步完成: {synced_count} 个文件")
    
    def _ask_interval(self):
        """手机友好的间隔时间设置"""
        print("\n检查间隔设置:")
        print("1. 1秒 (最快，耗电较多)")
        print("2. 2秒 (推荐)")
        print("3. 3秒 (平衡)")
        print("4. 5秒 (省电)")
        
        while True:
            choice = input("请选择 (1-4，默认2): ").strip()
            if not choice:
                choice = "2"
            
            if choice == "1":
                return 1.0
            elif choice == "2":
                return 2.0
            elif choice == "3":
                return 3.0
            elif choice == "4":
                return 5.0
            else:
                print("请输入 1-4")
    
    def start_monitoring(self):
        self.running = True
        
        # 询问检查间隔
        self.poll_interval = self._ask_interval()
        
        # 初始同步
        self._initial_sync()
        
        print(f"\n开始监控")
        print(f"源目录: {self.source_dir}")
        print(f"目标目录: {self.target_dir}")
        print(f"检查间隔: {self.poll_interval}秒")
        print(f"排除目录: {len(self.excluded_dirs)} 个")
        print("按 Ctrl+C 停止\n")
        
        last_status_time = time.time()
        
        try:
            while self.running:
                start_time = time.time()
                
                self._check_file_changes()
                
                current_time = time.time()
                if current_time - last_status_time >= 30:
                    print(f"监控中 {datetime.now().strftime('%H:%M:%S')} | "
                          f"文件数: {len(self.file_states)}")
                    last_status_time = current_time
                
                elapsed = time.time() - start_time
                sleep_time = max(0, self.poll_interval - elapsed)
                time.sleep(sleep_time)
                
        except KeyboardInterrupt:
            self.stop_monitoring()
    
    def stop_monitoring(self):
        self.running = False
        print("\n监控已停止")

def get_directory_input(prompt):
    """简化的目录输入"""
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
    """加载配置"""
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
    """配置排除目录"""
    excluded_dirs = set()
    
    print("\n排除目录设置:")
    print("输入要排除的目录名，直接回车结束")
    
    while True:
        dir_input = input("排除目录: ").strip()
        if not dir_input:
            break
        excluded_dirs.add(dir_input)
    
    # 保存配置
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
    print("文件监控工具")
    print("=" * 30)
    
    # 获取源目录
    source_dir = get_directory_input("源目录")
    
    # 获取目标目录
    target_dir = get_directory_input("目标目录")
    
    # 加载或配置排除目录
    excluded_dirs, config_file = load_config(source_dir)
    
    if not config_file.exists():
        print("首次运行，需要配置排除目录")
        excluded_dirs = configure_excluded_dirs(source_dir)
    else:
        reconfig = input("重新配置排除目录？(y/n): ").strip().lower()
        if reconfig == 'y':
            excluded_dirs = configure_excluded_dirs(source_dir)
    
    # 启动监控
    monitor = MobileFriendlyFileMonitor(source_dir, target_dir, excluded_dirs)
    monitor.start_monitoring()

if __name__ == '__main__':
    main()

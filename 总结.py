import os
from pathlib import Path

def get_directory_tree(start_path='.', max_depth=None):
    """
    递归获取目录树结构，显示文件和目录名称及大小
    
    Args:
        start_path: 起始路径，默认为当前目录
        max_depth: 最大遍历深度，None表示无限制
    """
    def format_size(size_bytes):
        """格式化文件大小显示"""
        if size_bytes == 0:
            return "0 B"
        size_names = ["B", "KB", "MB", "GB", "TB"]
        i = 0
        while size_bytes >= 1024 and i < len(size_names) - 1:
            size_bytes /= 1024.0
            i += 1
        return f"{size_bytes:.1f} {size_names[i]}"
    
    def traverse(path, depth=0):
        """递归遍历目录"""
        if max_depth is not None and depth > max_depth:
            return
            
        try:
            items = sorted(Path(path).iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
        except PermissionError:
            print("  " * depth + "📁 [权限不足，无法访问]")
            return
        except Exception as e:
            print("  " * depth + f"❌ [错误: {e}]")
            return
        
        for item in items:
            indent = "  " * depth
            
            if item.is_dir():
                try:
                    # 计算目录大小
                    dir_size = sum(f.stat().st_size for f in item.rglob('*') if f.is_file())
                    print(f"{indent}📁 {item.name}/ [{format_size(dir_size)}]")
                    traverse(item, depth + 1)
                except Exception as e:
                    print(f"{indent}📁 {item.name}/ [无法计算大小: {e}]")
            else:
                try:
                    file_size = item.stat().st_size
                    print(f"{indent}📄 {item.name} [{format_size(file_size)}]")
                except Exception as e:
                    print(f"{indent}📄 {item.name} [无法获取大小: {e}]")
    
    print(f"📍 目录树: {os.path.abspath(start_path)}")
    print("=" * 50)
    traverse(start_path)

if __name__ == "__main__":
    # 使用示例
    get_directory_tree()  # 当前目录
    
    # 或者指定特定目录
    # get_directory_tree("/path/to/directory")
    
    # 或者限制深度
    # get_directory_tree(max_depth=3)

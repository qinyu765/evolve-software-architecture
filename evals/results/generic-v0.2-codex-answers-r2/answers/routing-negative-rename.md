[src/click/utils.py:29](/evaluation-path/repository/src/click/utils.py:29) 的局部改动仅为将参数 `name` 及函数体中的引用改为 `value`：

```python
def _posixify(value: str) -> str:
    return "-".join(value.split()).lower()
```

函数体逻辑保持不变，未修改文件。
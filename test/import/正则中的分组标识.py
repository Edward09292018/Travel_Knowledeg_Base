import re

stripped_line = "````123~~~abc```````"

# 方法2: 保持原有的 match 方式，但更清晰
code_block_marker_match = re.match(r'^(`{3,}|~{3,}).*?(`{3,}|~{3,}).*?(`{3,}|~{3,})$', stripped_line)
if code_block_marker_match:
    marker1 = code_block_marker_match.group(1)
    marker2 = code_block_marker_match.group(2)
    marker3 = code_block_marker_match.group(3)
    print("\n原有方法结果:")
    print(f"标记1: {marker1}")
    print(f"标记2: {marker2}")
    print(f"标记3: {marker3}")
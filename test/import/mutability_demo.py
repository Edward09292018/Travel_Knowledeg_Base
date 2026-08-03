def line(title):
    print("\n" + "=" * 55)
    print(title)
    print("=" * 55)

line("一、不可变类型 (immutable)：int / float / bool / str / tuple / frozenset")

# int
x = 10
print("int   修改前:", x, "id:", id(x))
x += 1
print("int   修改后:", x, "id:", id(x), "-> id 变了，说明生成了新对象")

# str
s = "abc"
print("\nstr   修改前:", s, "id:", id(s))
s += "d"
print("str   修改后:", s, "id:", id(s), "-> id 变了")

# tuple 本身不可变：不能就地改元素
t = (1, 2, 3)
print("\ntuple:", t, "id:", id(t))
try:
    t[0] = 99
except TypeError as e:
    print("尝试 t[0]=99 报错:", e)

line("二、可变类型 (mutable)：list / dict / set / bytearray")

# list
lst = [1, 2, 3]
print("list  修改前:", lst, "id:", id(lst))
lst.append(4)
print("list  修改后:", lst, "id:", id(lst), "-> id 没变，原地修改")

# dict
d = {"a": 1}
print("\ndict  修改前:", d, "id:", id(d))
d["b"] = 2
print("dict  修改后:", d, "id:", id(d), "-> id 没变")

# set
st = {1, 2}
print("\nset   修改前:", st, "id:", id(st))
st.add(3)
print("set   修改后:", st, "id:", id(st), "-> id 没变")

line("三、可变 vs 不可变最容易踩的坑：函数传参 / 共享引用")

def try_change_int(n):
    n += 100  # 生成新对象，不影响外部

def try_change_list(items):
    items.append("added")  # 原地修改，影响外部

num = 1
try_change_int(num)
print("传 int 给函数后（外部）:", num, "-> 没被改（不可变）")

data = [1, 2]
try_change_list(data)
print("传 list 给函数后（外部）:", data, "-> 被改了（可变）")

# 共享引用
a = [1, 2, 3]
b = a
b.append(4)
print("\na =", a, "  b = a 后对 b 追加 -> a 也变了（同一对象）")
print("a is b ?", a is b)

line("四、判断某类型是否可变的通用方法：看它有没有 __hash__")
for obj in [1, "s", (1, 2), [1], {1: 2}, {1, 2}]:
    hashable = obj.__hash__ is not None
    print(f"{str(obj):10} 可哈希={hashable}  -> {'不可变(通常)' if hashable else '可变'}")

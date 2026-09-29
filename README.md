# 数字分身 · 知识本体

数字分身要回答「我是谁、会什么、经历过什么、在意什么」，先得有一份结构化的个人知识，而不是一堆散落的句子。这个模块就是那份知识的本体：类别、关系、个体、断言，以及沿这些关系做的轻量推理。

## 本体里有什么

内置本体从「事物」分出主体、人物、组织、地点、事件、经历、项目、技能、偏好、目标、观点、记忆和主题。主体是数字分身自己，标识固定为 `self`，可以同时是一个人物。其余这些类别互不相交；经历是事件的子类，因此询问「有哪些事件」时会带上经历。

常用关系：

| 关系 | 含义 | 特性 |
| --- | --- | --- |
| 认识 `knows` | 人物之间互相认识 | 对称 |
| 掌握 `has_skill` | 人物掌握技能 | 逆关系是「技能属于」 |
| 参与 `participated_in` | 参与事件或项目 | |
| 隶属于 `member_of` | 人物属于组织 | |
| 位于 `located_in` | 所在地点 | 传递，逆关系是「包含」 |
| 偏好 `prefers` | 偏好某种风格或主题 | |
| 追求 `pursues` | 主体追求目标 | |
| 持有 `holds_belief` | 主体持有观点 | |
| 记得 `recalls` | 主体记得一段记忆 | |
| 关于 `about` | 这段知识在谈论什么 | |
| 从属于 `part_of` | 事件、项目或组织从属于更大的项目或组织 | 传递 |
| 相关 `related_to` | 两个事物相关 | 对称 |

属性包括名称、别名、摘要、熟练度、强度、开始/结束时间和优先级。熟练度和强度限制在 0 到 1。

类型按开放世界理解：个体还没有类型时，不判断它是否违反定义域或值域。一旦标了类型，就会检查子类、不相交、定义域、值域和函数性（例如名称只能有一个）。`--lenient` 会收下后四类问题，留给 `ontology check` 报告；数据类型和取值范围始终有效。

## 安装

```bash
python3 -m pip install -e ".[dev]"
```

## 命令行

```bash
ontology init
ontology import-triples examples/demo.triples
ontology show self
ontology query --type Event
ontology query --label 林
ontology paths self place:zhejiang
ontology check
```

三元组每行是「主体 关系 客体」，`#` 开头是注释。关系可以用中文，也可以用本体里的英文标识：

```
self 掌握 skill:python
skill:python 类型 Skill
skill:python 名称 Python
skill:python 熟练度 1
```

知识库默认写在当前目录的 `ontology.db`，也可以用 `--db` 或环境变量 `ONTOLOGY_DB` 指定。

## Python

```python
from shuzifensheng.ontology import OntologyStore

with OntologyStore("ontology.db") as onto:
    onto.add_individual("skill:python", types=["Skill"], labels={"zh": "Python"})
    onto.assert_data("skill:python", "name", "Python")
    onto.assert_data("skill:python", "proficiency", 1)
    onto.assert_object("self", "has_skill", "skill:python")
    view = onto.get("self")
    onto.check()
```

`get` 返回一跳之内的属性和关系，并自动补上逆关系和对称关系。传递关系用 `expand` 沿链条展开。`export_dict` / `import_dict` 使用 JSON 文档 `shuzifensheng.ontology` 版本 1。

## 测试

```bash
python3 -m pytest -q
```

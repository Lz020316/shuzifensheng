"""知识本体错误。"""


class OntologyError(Exception):
    """知识本体操作失败。"""


class ValidationError(OntologyError):
    """断言或取值不符合本体约束。"""


class SchemaError(OntologyError):
    """类别或关系的定义互相冲突。"""


class NotFoundError(OntologyError):
    """类别、关系或个体不存在。"""

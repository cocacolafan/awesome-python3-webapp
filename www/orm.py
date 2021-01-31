__author__ = 'Cola Fan'

import asyncio, logging
from typing import Mapping
import aiomysql

def log(sql, args=()):
    logging.info('SQL: %s' % sql)

async def create_pool(loop, **kw):
    logging.info('create database connection pool...')
    global __pool
    __pool = await aiomysql.create_pool(
        host = kw.get('host', 'localhost'),
        port = kw.get('port', 3306),
        user = kw['user'],
        password = kw['password'],
        db = kw['db'],
        charset = kw.get('charset', 'utf8'),
        autocommit = kw.get('autocommit', True),
        maxsize = kw.get('maxsize', 10),
        minsize = kw.get('minsize', 1),
        loop = loop
    )

async def select(sql, args, size=None):
    log(sql, args)
    global __pool
    with (await __pool) as conn:
        cur = await conn.cursor(aiomysql.DictCursor)
        await cur.execute(sql.replace('?', '%s'), args or ())
        if size:
            rs = await cur.fetchmany(size)
        else:
            rs = await cur.fetchall()
        await cur.close()
        logging.info('rows returned: %s' % len(rs))
        return rs

async def excute(sql, args):
    log(sql)
    with (await __pool) as conn:
        try:
            cur = await conn.cursor()
            await cur.execute(sql.replace('?', '%s'), args) # 由于python占位不能用%s，否则必须格式化，所以用？代替，然后在replace回来，通过aiomysql的excute格式化数值，创建一个database
            affected = cur.rowcount
            await cur.close()
        except BaseException as e:
            raise
        return affected

def create_args_string(num):
    L = []
    for n in range(num):
        L.append('?')
    return ", ".join(L)

class Field(object):
    def __init__(self, name, column_type, primary_key, default):
        self.name = name
        self.column_type = column_type
        self.primary_key = primary_key
        self.default = default

    def __str__(self):
        return '<%s, %s:%s>' % (self.__class__.__name__, self.column_type, self.name)

class StringField(Field):
    def __init__(self, name=None, primary_key=False, default=None, ddl='varchar(100)'):
        super().__init__(name, ddl, primary_key, default)

class BooleanField(Field):
    def __init__(self, name=None, default=False):
        super().__init__(name, 'boolean', False, default)

class IntegerField(Field):
    def __init__(self, name=None, primary_key=False, default=0):
        super().__init__(name, 'bigint', primary_key, default)

class FloatField(Field):
    def __init__(self, name=None, primary_key=False, default=0.0):
        super().__init__(name, 'real', primary_key, default)

class TextField(Field):
    def __init__(self, name=None, default=None):
        super().__init__(name, 'text', False, default)

class ModelMetaclass(type):
    def __new__(cls, name, bases, attrs):
        if name == 'Model':
            return type.__new__(cls, name, bases, attrs)
        tableName = attrs.get('__table__', None) or name  # 如果类自己定义了__table__便用自己定义的，没有返回默认值None，然后执行or后面的，将__table__设置为类的名字
        logging.info('found model: %s (table: %s)' % (name, tableName))
        mappings = dict()
        fields = []   # primary_Key为True的XXXField不存在这里，保存在primaryKey中
        primaryKey = None
        for k, v in attrs.items():
            if isinstance(v, Field):
                logging.info('  found mapping: %s ==> %s' % (k, v)) # 找到了属性，他映射到一个XXXField类的数据
                mappings[k] = v
                if v.primary_key:   # 每个XXField类的主键参数默认是0，当有好几个XXXField属性时，看哪个primary_Key参数设为True，哪个XXXField类就是主键
                    # 找到主键
                    if primaryKey:
                        raise RuntimeError('Duplicate primary key for field: %s' % k)  # 这句话处理了attrs中要是有两个primary_Key是True的情况，抛出错误说明，告诉调用者主键有了新的值
                    primaryKey = k #主键是哪个XXXField类由primaryKey储存
                else:
                    fields.append(k)  # 储存着非主键True的其他XXXField类的属性名
        if not primaryKey:
            raise RuntimeError('Primary key is not founded.')
        for k in mappings.keys():  # 清洗attrs，把已经通过__new__方法拿出来的XXXField属性从attrs删除掉，然后再用剩下的属性创建类
            attrs.pop(k)
        escaped_fields = list(map(lambda f: '`%s`' % f, fields))  # 转义field名称: field[]==>`field[]`
        attrs['__mappings__'] = mappings   # 挑出来的XXXField类字典保存到类的__mappings__属性中
        attrs['__table__'] = tableName
        attrs['__primary_key__'] = primaryKey  # 设置为主键的属性名
        attrs['__fields__'] = fields # 除去设置为主键值属性的属性名
        attrs['__select__'] = 'select `%s`, %s from `%s`' % (primaryKey, ', '.join(escaped_fields), tableName)
        attrs['__insert__'] = 'insert into `%s` (%s, `%s`) values (%s)' % (tableName, ', '.join(escaped_fields), primaryKey, create_args_string(len(escaped_fields) + 1))
        attrs['__update__'] = 'update `%s` set %s where `%s`=?' % (tableName, ', '.join(map(lambda f: '`%s`=?' % (mappings.get(f).name or f), fields)), primaryKey)
        attrs['__delete__'] = 'delete from `%s` where `%s`=?' % (tableName, primaryKey)
        return type.__new__(cls, name, bases, attrs)

class Model(dict, metaclass=ModelMetaclass):
    def __init__(self, **kw):
        super().__init__(**kw)

    def __getattr__(self, key):    # 继承dict类，重写__getattr__方法:将本来需要self[key]调用转化为通过self.key也能调用
        try:
            return self[key]       # 因为继承了dict，所以会调用父类的__item__方法，使得Model也可以直接以self[key]存储东西
        except KeyError:
            raise AttributeError(r"'Model' object has no attribute '%s'" % key)
    # 设置自身属性：
    def __setattr__(self, key, value):
        self[key] = value
    # 通过属性返回一个lazy function：
    def getValue(self, key):
        return getattr(self, key, None)   # 返回一个惰性函数
         
    def getValueOrDefault(self, key):  # 调用key的值，自身的属性中没有这个值的时候用储存在__mapping__中的同名属性默认值返回
        value = getattr(self, key, None)
        if value is None:  # 如果属性中没有直接叫做key的属性，那么在__mapping__属性字典中存储的键值对中寻找
            field = self.__mappings__[key]
            if field.default is not None:  # 如果__maooing__字典中找到了key属性，判断Field的default是否是一个lazy function，是的话执行它获得属性值，否则default本身就是属性值
                value = field.default() if callable(field.default) else field.default   # 避免default储存的是一个惰性函数
                logging.debug('using default value for %s: %s' % (key, str(value)))
                setattr(self, key, value)  # 把在映射库__mapping__中的属性给调出来
        return value
    
    # 再增加自定义的类方法：
    @classmethod
    async def findAll(cls, where=None, args=None, **kw):
        'find object by where clause. '
        sql = [cls.__select__]  # __select__属性是一个字符串,这个作为sql的第一个值sql[0]
        if where:   # 如果指定了在哪里找
            sql.append('where')            
            sql.append(where)            
        if args is None:
            args = []
        # 解析参数并执行：
        orderBy = kw.get('orderBy', None) # 解析自定义的参数
        if orderBy:
            sql.append('order by')            
            sql.append(orderBy)
        limit = kw.get('limit', None)
        if limit is not None:  # 只要不是None就行，0也可以
            sql.append('limit')
            if isinstance(limit, int):
                sql.append('?')
                args.append(limit)  # 是数字的话不存储在sql，而是存储在args
            elif isinstance(limit, tuple) and len(limit) == 2:
                sql.append('?,?')
                args.extend(limit)  # 把tuple的元素一个一个加到args末尾
            else:
                raise ValueError("Invalid limit value: %s" % str(limit))
        rs = await select(' '.join(sql), args)  # 🌂?????肯能是一个魔法方法
        return [cls(**r) for r in rs]   # 🌂

    @classmethod
    async def findNumber(cls, selectField, where=None, args=None):
        'find number by select and where. '
        sql = ['select %s _num_from `%s`' % (selectField, cls.__table__)]
        if where:
            sql.append('where')
            sql.append(where)
        rs = await select(' '.join(sql), args, 1)
        if len(rs) == 0:
            return None
        return rs[0]['_num_']

    @classmethod
    async def find(cls, pk):
        'find object by primary key. '
        rs = await select('%s where `%s`=?' % (cls.__select__, cls.__primary_key__), [pk], 1)
        if len(rs) == 0:
            return None
        return cls(**rs[0])

    async def save(self):
        args = list(map(self.getValueOrDefault, self.__fields__))
        args.append(self.getValueOrDefault(self.__primary_key__))
        rows = await excute(self.__insert__, args)
        if rows != 1:
            logging.warn('failed to insert record: afffect rows: %s' % rows)

    async def update(self):
        args = list(map(self.getValue, self.__fields__))
        args.append(self.getValue(self.__primary_key__))
        rows = await excute(self.__update__, args)
        if rows != 1:
            logging.warn('failed to update by primary key: affected rows: %s' % rows)
    
    async def remove(self):
        args = [self.getValue(self.__primary_key__)]
        rows = await excute(self.__delete__, args)
        if rows != 1:
            logging.warn('failed to remove by primary key: affected rows: %s' % rows)


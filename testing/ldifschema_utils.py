from ldap.schema import AttributeType, ObjectClass

import re

atypeRegex = re.compile('^attributeTypes:\s', re.IGNORECASE)
obclassRegex = re.compile('^objectClasses:\s', re.IGNORECASE)


class OpenDjSchema:

    def __init__(self, schema_file):
        self.schema_file = schema_file
        self.schema=[]
        self.attribute_names = []
        self.class_names = []
        self.lines = []
        self._startread()
        self.parse_lines()

    def _make_line(self, _tmp):
        if _tmp:
            nl = ''.join(_tmp)
            while '  ' in nl:
                nl=nl.replace('  ', ' ')
            self.lines.append(nl)
        
    def _startread(self):
        f = open(self.schema_file)
        _tmp = []
        for l in f:
            ls = l.strip()
            if atypeRegex.match(ls) or obclassRegex.match(ls):
                self._make_line(_tmp)
                _tmp = []
                _tmp.append(l[:-1])
            elif l[0] == ' ':
                _tmp.append(l[1:-1])
            else:
                self.lines.append(l[:-1])
        self._make_line(_tmp)
            
    def parse_lines(self):
        for l in self.lines:
            n = l.find(':')
            if atypeRegex.match(l):
                a = AttributeType(l[n+1:])
                self.schema.append(a)
                for name in a.names:
                    self.attribute_names.append(name)
                
            elif obclassRegex.match(l):
                c = ObjectClass(l[n+1:])
                self.schema.append(c)
                for name in c.names:
                    self.class_names.append(name)
            else:
                self.schema.append(l)

    def get_attribute_by_name(self, name):
        
        for o in self.schema:
           if o.__class__ is AttributeType:
                if name in o.names:
                    return o

    def get_class_by_name(self, name):
        for o in self.schema:
            if o.__class__ is ObjectClass:            
                if name in o.names:
                    return o
    def add_attribute_to_class(self, class_name, attribute_name):
        c = self.get_class_by_name(class_name)
        if c:
            if not attribute_name in c.may:
                may_list = list(c.may)
                may_list.append(attribute_name)
                c.may = tuple(may_list)

    def write(self, file_name=None):
        if not file_name:
            file_name = self.schema_file
        with open(file_name, 'w') as f:
            for o in self.schema:
                if  o.__class__ is str:
                    f.write(o+'\n')
                elif o.__class__ is AttributeType:
                    f.write('attributeTypes: {}\n'.format(o.__str__()))
                elif o.__class__ is ObjectClass:
                    f.write('objectClasses: {}\n'.format(o.__str__()))
    def add_attribute(self, oid, names, syntax, origin,
                      desc='',
                      sup=(),
                      substr='',
                      equality='',
                      single_value=False,
                      obsolete=False,
                      ordering=None,
                      x_ordered=None,
                      syntax_len=None,
                      collective=False,
                      no_user_mod=False,
                      usage=0,
                      ):
        a = AttributeType()
        a.oid = oid
        a.names = tuple(names)
        a.syntax = syntax
        a.x_origin = origin
        a.desc = desc
        a.sup = sup
        a.equality = equality
        a.substr = substr
        a.single_value = single_value
        a.obsolete = obsolete
        a.x_ordered = x_ordered
        a.ordering = ordering
        a.syntax_len = syntax_len
        a.collective = collective
        a.no_user_mod = no_user_mod
        a.usage = usage

        for i,o in enumerate(self.schema):
            if o.__class__ is ObjectClass:
                break
        self.schema.insert(i,a)

if __name__ == "__main__":

    m=OpenDjSchema('/tmp/96-eduperson.ldif')

    m.add_attribute(oid='oxSectorIdentifierURI-oid',
                    names=['oxSectorIdentifierURI'],
                    syntax='1.3.6.1.4.1.1466.115.121.1.15',
                    origin='Gluu created attribute',
                    desc='ox Sector Identifier URI',
                    equality='caseIgnoreMatch',
                    substr='caseIgnoreSubstringsMatch')
                    
    m.write('/tmp/x.lidf')






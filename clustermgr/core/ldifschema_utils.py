from ldap.schema import AttributeType, ObjectClass, LDAPSyntax
from ldif import LDIFParser
import os

class OpenDjSchema(LDIFParser):

    def __init__(self, schema_file):
        self.attribute_names = []
        self.class_names = []
        self.schema_file = schema_file
        LDIFParser.__init__(self,open(schema_file, 'rb'))
        self.parse()

    def handle(self, dn, entry):
        self.schema={
                    'dn': dn,
                    'objectClass': entry['objectClass'],
                    'objectClasses': [],
                    'attributeTypes': [],
                    'ldapSyntaxes': entry.get('ldapSyntaxes',[]),
                    }
        
        for ocls in entry.get('objectClasses',[]):
            o = ObjectClass(ocls)
            self.schema['objectClasses'].append(o)
            for name in o.names:
                self.class_names.append(name)

        for atyp in entry.get('attributeTypes',[]):
            a = AttributeType(atyp)
            self.schema['attributeTypes'].append(a)
            for name in a.names:
                self.attribute_names.append(name)

    def get_attribute_by_name(self, name):
        for o in self.schema['attributeTypes']:
            if name in o.names:
                return o

    def get_class_by_name(self, name):
        for o in self.schema['objectClasses']:
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
            f.write('dn: {}\n'.format(self.schema['dn']))
            for oc in self.schema['objectClass']:
                f.write('objectClass: {}\n'.format(oc))
            
            for syn in  self.schema['ldapSyntaxes']:
                f.write('ldapSyntaxes: {}\n'.format(syn))
            
            for atyp in  self.schema['attributeTypes']:
                f.write('attributeTypes: {}\n'.format(atyp.__str__()))
            
            for ocls in self.schema['objectClasses']:
                f.write('objectClasses: {}\n'.format(ocls.__str__()))

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

        self.schema['attributeTypes'].append(a)
        for name in a.names:
            self.attribute_names.append(name)

    def add_attributes(self, s):
        a = AttributeType(s)
        self.schema['attributeTypes'].append(a)
        for name in a.names:
            self.attribute_names.append(name)

    def add_classs(self, s):
        o = ObjectClass(s)
        self.schema['objectClasses'].append(o)
        for name in o.names:
            self.class_names.append(name)

def parse_open_ldap_schema(fn):
    f = open(fn).readlines()
    
    entry_finished = True
    new_entry= []
    new_object = []
    attributes = []
    objectclasses = []

    for i,l in enumerate(f):

        if l.lower().startswith('attributetype') or l.lower().startswith('objectclass') or (i==len(f)-1):
            entry_finished = False
            objs = ' '.join(new_entry)

            if objs.lower().startswith('attributetype'):
                attributes.append(AttributeType(objs[14:]))
            elif objs.lower().startswith('objectclass'):
                objectclasses.append(ObjectClass(objs[12:]))
                
            new_entry = []

        if not entry_finished:
            if not l.startswith('#'):
                ls = l.strip()
                if ls:
                    new_entry.append(ls)

    
    return {'attributes': attributes, 'objectclasses': objectclasses}

if __name__ == "__main__":

    """
    m=OpenDjSchema('/tmp/schema/96-eduperson.ldif')

    m.add_attribute(oid='oxSectorIdentifierURI-oid',
                    names=['oxSectorIdentifierURI'],
                    syntax='1.3.6.1.4.1.1466.115.121.1.15',
                    origin='Gluu created attribute',
                    desc='ox Sector Identifier URI',
                    equality='caseIgnoreMatch',
                    substr='caseIgnoreSubstringsMatch')
                    
    m.write('/tmp/x.lidf')


    """
    
    for s in os.listdir('/tmp/schema/'):
        print "processing", s
        m=OpenDjSchema('/tmp/schema/'+s)
        m.write('/tmp/x/' + s)




"""Exercise native math generation; no PDF/store/Office dependency for unit tests."""
import ast
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as E
import zipfile

APP=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(APP))
from backend.safety import DomainError
from backend.document_quality import inspect,math_issues

source=ast.parse((APP/'backend/office_extract.py').read_text('utf-8-sig'))
# These generation/signature functions do not use the PDF adapter.
source.body=[n for n in source.body if not isinstance(n,ast.ImportFrom) or not (n.level==1 and n.module is None and any(a.name=='pdf' for a in n.names))]
env={'__name__':'backend.office_extract','__package__':'backend'}
exec(compile(source,'office_extract.py','exec'),env)
MathBuilder=env['MathBuilder'];create_docx=env['create_docx'];math_signature=env['math_signature'];M=env['M']

def fixture():
    return {'schema_version':1,'math':{'R':{'bold_upright':'R'}},'blocks':[
        {'runs':['Source-frame angular velocity ',{'math':{'pre':[{'sub':['ω','WI']},'I','']}},'.']},
        {'equation':{'underbrace':[{'product':{'lower':'k=i','upper':'j−1','body':{'ref':'R'}}},{'sub':['R','ij']}]},'number':'11'},
        {'equation':{'overbrace':[['a','+','b'],'c']}},
        {'equation':{'pre':['T','i','j']}},
        {'equation':{'pre':['x','','A']}}]}

class MathTests(unittest.TestCase):
    def test_native_script_order_and_intentional_single_side(self):
        node=MathBuilder({}).build({'pre':['ω','I','']})[0]
        self.assertEqual([c.tag.rsplit('}',1)[-1] for c in node],['sub','sup','e'])
        self.assertEqual(''.join(node.find('{'+M+'}sub').itertext()),'I')
        self.assertEqual(math_issues(env['tag'](M,'oMath',node)),[])

    def test_empty_base_and_both_empty_scripts_are_rejected(self):
        for spec in ({'pre':['','i','']},{'pre':['x','','']},{'underbrace':['x','']},{'underbrace':['','i']}):
            with self.assertRaises(DomainError):MathBuilder({}).build(spec)
        empty=env['tag'](M,'oMath',env['tag'](M,'sPre',env['tag'](M,'sub'),env['tag'](M,'sup'),env['tag'](M,'e',*MathBuilder({}).build('x'))))
        self.assertIn('empty_math_argument:sPre/scripts',math_issues(empty))

    def test_underbrace_and_product_preserve_native_arguments(self):
        node=MathBuilder({}).build({'underbrace':[{'product':{'lower':'i=1','upper':'n','body':'x'}},'P']})[0]
        self.assertEqual(node.tag,'{'+M+'}limLow')
        self.assertEqual(node.find('.//{'+M+'}groupChrPr/{'+M+'}chr').get('{'+M+'}val'),'⏟')
        self.assertEqual(node.find('.//{'+M+'}naryPr/{'+M+'}chr').get('{'+M+'}val'),'∏')
        self.assertEqual(node.find('.//{'+M+'}naryPr/{'+M+'}limLoc').get('{'+M+'}val'),'undOvr')

    def test_inline_and_named_math_produce_same_structure(self):
        with tempfile.TemporaryDirectory() as t:
            a,b=Path(t)/'a.docx',Path(t)/'b.docx'
            expression={'sub':['x','i']}
            create_docx({'schema_version':1,'math':{'x':expression},'blocks':[{'runs':['a',{'math':'x'}]},{'equation':'x'}]},a)
            create_docx({'schema_version':1,'blocks':[{'runs':['a',{'math':expression}]},{'equation':expression}]},b)
            self.assertEqual(math_signature(a),math_signature(b))
            self.assertTrue(inspect(b,'word')['passed'])

    def test_fixture_is_editable_and_passes_shared_quality_gate(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'native.docx';self.assertEqual(create_docx(fixture(),p),5)
            self.assertTrue(inspect(p,'word')['passed'])
            with zipfile.ZipFile(p) as z:
                root=E.fromstring(z.read('word/document.xml'))
                self.assertEqual(len(root.findall('.//{'+M+'}sPre')),3)
                self.assertEqual(len(root.findall('.//{'+M+'}groupChr')),2)

    def test_unknown_reference_and_cycles_still_fail(self):
        with self.assertRaises(DomainError):MathBuilder({}).build({'ref':'missing'})
        with self.assertRaises(DomainError):MathBuilder({'x':{'ref':'x'}}).build({'ref':'x'})

if __name__=='__main__':unittest.main(verbosity=2)

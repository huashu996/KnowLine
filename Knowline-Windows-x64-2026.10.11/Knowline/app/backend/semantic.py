"""Small offline encoder; reuse the app's Python/NumPy instead of another runtime."""
import hashlib,json,os,sys
from pathlib import Path
def serve(project):
 from .layout import app_dir
 app=app_dir(project);runtime=app/'.semantic-runtime'
 import numpy as np
 sys.path.insert(0,str(runtime))
 import onnxruntime as ort
 from tokenizers import Tokenizer,AddedToken
 folder=next((app/'.semantic-models').glob('models--Qdrant--bge-small-zh-v1.5/snapshots/*'))
 model_file=folder/'model_optimized.onnx';model_hash=hashlib.sha256(model_file.read_bytes()).hexdigest()
 config=json.loads((folder/'tokenizer_config.json').read_text('utf-8'));base=json.loads((folder/'config.json').read_text('utf-8'))
 tokenizer=Tokenizer.from_file(str(folder/'tokenizer.json'))
 tokenizer.enable_truncation(max_length=min(v for v in [config.get('model_max_length'),config.get('max_length')] if isinstance(v,int) and 0<v<100000))
 for value in json.loads((folder/'special_tokens_map.json').read_text('utf-8')).values():
  for token in value if isinstance(value,list) else [value]:tokenizer.add_special_tokens([token if isinstance(token,str) else AddedToken(**token)])
 pad=tokenizer.padding or {};name=pad.get('pad_token') or config['pad_token']
 tokenizer.enable_padding(direction=pad.get('direction','right'),pad_id=pad.get('pad_id',base.get('pad_token_id',tokenizer.token_to_id(name))),pad_type_id=pad.get('pad_type_id',0),pad_token=name,pad_to_multiple_of=pad.get('pad_to_multiple_of'),length=None)
 options=ort.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=2
 model=ort.InferenceSession(str(model_file),sess_options=options,providers=['CPUExecutionProvider'])
 inputs={i.name for i in model.get_inputs()}
 for line in sys.stdin:
  try:
   request=json.loads(line);texts=request['texts']
   if not isinstance(texts,list) or len(texts)>128 or any(not isinstance(t,str) or len(t)>20000 for t in texts):raise ValueError('invalid texts')
   vectors=[]
   for start in range(0,len(texts),16):
    encoded=tokenizer.encode_batch(texts[start:start+16]);ids=np.asarray([e.ids for e in encoded],dtype=np.int64)
    values={'input_ids':ids}
    if 'attention_mask' in inputs:values['attention_mask']=np.asarray([e.attention_mask for e in encoded],dtype=np.int64)
    if 'token_type_ids' in inputs:values['token_type_ids']=np.zeros_like(ids)
    output=model.run(None,values)[0];output=output[:,0] if output.ndim==3 else output
    vectors.extend((output/np.maximum(np.linalg.norm(output,axis=1,keepdims=True),1e-12)).tolist())
   answer={'vectors':vectors,'model_id':'fastembed-0.8.1:BAAI/bge-small-zh-v1.5:'+model_hash,'encoding_backend':'onnx_cpu_cls_l2','learned_model':True,'dimensions':512}
   if request.get('dependency_report'):answer['loaded_runtime_packages']=sorted({Path(module.__file__).relative_to(runtime).parts[0] for module in sys.modules.values() if getattr(module,'__file__',None) and Path(module.__file__).is_relative_to(runtime)})
   print(json.dumps(answer),flush=True)
  except Exception as error:print(json.dumps({'error':type(error).__name__+': '+str(error)}),flush=True)

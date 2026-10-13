"""Keep task deletion confirmation and cleanup feedback aligned with the API."""
from pathlib import Path
import re


def patch(app):
    html = (app / 'dist/index.html').read_text('utf-8')
    path = app / 'dist/assets' / re.search(r'src="/assets/([^"?]+\.js)', html).group(1)
    source = path.read_text('utf-8')
    # Migrate the earlier shared-output wording to the user's resource-only rule.
    source=source.replace('原始资料和仍被其他任务或知识库引用的文件将保留。','知序内已登记的资源及其原始证据将保留，其余任务文件全部删除。')
    source=source.replace('Source resources and files still used by other tasks or knowledge bases will be kept.','Registered Knowline resources and their original evidence will be kept; all other task files will be deleted.')
    source=source.replace('Ze?.storage_cleanup?kwJobDeletionMessage(Ze.storage_cleanup,r==="zh"):c(S)','Ze?.cleanup_scope==="job_outputs"?kwJobDeletionMessage(Ze.storage_cleanup,r==="zh"):c(S)')
    source=source.replace('任务及其独占产物已删除；原始资料和仍在使用的共享文件已保留。','任务文件已清理；知序内已登记的资源及其原始证据已保留。')
    source=source.replace('Tasks and their exclusive outputs deleted; source resources and shared files still in use were kept.','Task files cleaned up; registered Knowline resources and their original evidence were kept.')
    changes = {
        '删除所选任务？原始资料和产物文件保留。': '删除所选任务及其产物文件？此操作不可撤销。知序内已登记的资源及其原始证据将保留，其余任务文件全部删除。',
        'Delete selected tasks? Source and output files are kept.': 'Delete selected tasks and their output files? This cannot be undone. Registered Knowline resources and their original evidence will be kept; all other task files will be deleted.',
        '删除此任务？原始资料将保留。': '删除此任务及其产物文件？此操作不可撤销。知序内已登记的资源及其原始证据将保留，其余任务文件全部删除。',
        'Delete this task? Source resources will be kept.': 'Delete this task and its output files? This cannot be undone. Registered Knowline resources and their original evidence will be kept; all other task files will be deleted.',
        'S&&yt(c(S)),await pt(J,ve),Ze': 'S&&yt(Ze?.cleanup_scope==="job_outputs"?kwJobDeletionMessage(Ze.storage_cleanup,r==="zh"):c(S)),await pt(J,ve),Ze',
    }
    for old,new in changes.items():
        if source.count(new)==1:continue
        if source.count(old)!=1:raise ValueError('Unexpected task deletion UI: '+old)
        source=source.replace(old,new,1)
    if 'function kwJobDeletionMessage(' not in source:
        source+='''
function kwJobDeletionMessage(cleanup,zh){
  if(cleanup.state==="pending")return zh?"任务已删除；部分文件仍被占用或尚未清理，将自动重试。":"Tasks deleted; some files are still in use or awaiting cleanup. Cleanup will retry automatically.";
  if(cleanup.state==="shared_references_retained")return zh?"任务文件已清理；知序内已登记的资源及其原始证据已保留。":"Task files cleaned up; registered Knowline resources and their original evidence were kept.";
  return zh?"任务及其产物文件已删除。":"Tasks and their output files deleted.";
}
'''
    path.write_text(source,encoding='utf-8')
    return path


if __name__=='__main__':
    print(patch(Path(__file__).resolve().parents[1]))

# 사용자 비밀번호 해시 생성기:  python make_user.py <아이디> <비밀번호>
import sys, json
from werkzeug.security import generate_password_hash
if len(sys.argv)!=3:
    print('사용법: python make_user.py <아이디> <비밀번호>'); sys.exit(1)
u,p=sys.argv[1],sys.argv[2]
print(json.dumps({u: generate_password_hash(p)}, ensure_ascii=False))

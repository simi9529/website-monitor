"""Create reusable VAPID keys without writing the private key into the repo."""

import argparse
import base64
import json
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--private-key', required=True, type=Path, help='저장소 밖의 비밀키 파일 경로')
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    private = args.private_key.resolve()
    if private.is_relative_to(repo):
        parser.error('비밀키는 공개 저장소 밖에 저장해야 합니다')
    private.parent.mkdir(parents=True, exist_ok=True)
    if not private.exists():
        key = ec.generate_private_key(ec.SECP256R1())
        encoded = base64.urlsafe_b64encode(key.private_numbers().private_value.to_bytes(32, 'big')).rstrip(b'=')
        with private.open('xb') as file:
            private.chmod(0o600)
            file.write(encoded)
    raw = base64.urlsafe_b64decode(private.read_text().strip() + '===')
    if len(raw) != 32:
        parser.error('비밀키 파일 형식을 확인하세요')
    key = ec.derive_private_key(int.from_bytes(raw, 'big'), ec.SECP256R1())
    public = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    config = {'publicKey': base64.urlsafe_b64encode(public).rstrip(b'=').decode()}
    (repo / 'docs' / 'config.json').write_text(json.dumps(config, indent=2) + '\n')
    print('공개키 설정을 갱신했습니다. 비밀키 값은 출력하지 않았습니다. 기존 키는 재사용했습니다.')


if __name__ == '__main__':
    main()

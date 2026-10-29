# Автоматический прогон всех замеров 
import csv
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent   # папка проекта
RESULTS = ROOT/'results'                 # папка с результатами
RESULTS.mkdir(exist_ok=True)

def command(*args, env=None, capture=False):
    return subprocess.run(['docker','compose',*args], cwd=ROOT, env=env,
                          check=True, text=True, capture_output=capture)

# Пересоздать контейнер search с нужной версией сервиса (SERVICE_VERSION) и дождаться его готовности
def restart(version):
    env = {**os.environ, 'SERVICE_VERSION':version}
    command('stop','--timeout','1','search',env=env)
    command('up','-d','--no-build','--no-deps','--force-recreate','--wait','--wait-timeout','60','search',env=env)

# Команда запуска нагрузочного скрипта внутри контейнера search
def load_command(mode, clients, name):
    return ['docker','compose','exec','-T','search','python','load.py',
            '--mode',mode,'--clients',str(clients),'--rate','5',
            '--duration','60','--warmup','10','--timeout','30',
            '--output',f'/tmp/{name}.json']

# Скопировать файл из контейнера search на компьютер
def copy(source, destination):
    command('cp',f'search:{source}',str(destination))

def main():
    summary=[]
    # Сведения о среде environment.json.
    metadata={'started_utc':datetime.now(timezone.utc).isoformat(),
              'docker':subprocess.check_output(['docker','info','--format','{{json .}}'],text=True)}
    # Лишние настройки хоста и пути не включаются в результаты
    info=json.loads(metadata.pop('docker'))
    metadata['docker']={k:info[k] for k in ['ServerVersion','NCPU','MemTotal','Architecture','KernelVersion','OperatingSystem']}
    metadata['python']=command('exec','-T','search','python','--version',capture=True).stdout.strip()
    metadata['packages']=command('exec','-T','search','pip','freeze',capture=True).stdout.splitlines()
    (RESULTS/'environment.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2))
    # 15 замеров 
    for version in ['sync','blocking_async','async']:
        for mode,clients in [('closed',1),('closed',10),('closed',40),('closed',80),('open',1)]:
            # Имя замера
            name=f'{version}_{"C"+str(clients) if mode=="closed" else "rate5"}'
            print('START',name,datetime.now(timezone.utc).isoformat(),flush=True)
            restart(version)
            with (RESULTS/f'{name}.log').open('w') as log:
                # Запустить нагрузку в фоне
                process=subprocess.Popen(load_command(mode,clients,name),cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
                # под нагрузкой снять py-spy dump версии blocking_async снимок того, чем занят основной поток
                if version=='blocking_async' and clients==10:
                    time.sleep(15)
                    dump=command('exec','-T','-u','root','search','py-spy','dump','--pid','1',capture=True)
                    (RESULTS/'blocking_async_dump.txt').write_text(dump.stdout)
                if process.wait()!=0:
                    raise RuntimeError(f'Ошибка нагрузки: {name}.log')
            # Забрать результат из контейнера и добавить строку в сводную таблицу
            copy(f'/tmp/{name}.json',RESULTS/f'{name}.json')
            data=json.loads((RESULTS/f'{name}.json').read_text())
            row={'version':version,'mode':f'C={clients}' if mode=='closed' else '5 req/s',
                 **data['search'],'health_p95_ms':data['health']['p95_ms']}
            summary.append(row)
            (RESULTS/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
            print('DONE',name,json.dumps(row),flush=True)
    # Профили py-spy
    # Профили снимаются отдельно, чтобы профилировщик не влиял на таблицу замеров
    for idle in [False,True]:
        name='sync_profile_idle' if idle else 'sync_profile'
        print('START',name,flush=True)
        restart('sync')
        with (RESULTS/f'{name}.log').open('w') as log:
            # Нагрузка C=10 в фоне через 10 с (после прогрева)запись профиля на 60 с
            process=subprocess.Popen(load_command('closed',10,name),cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
            time.sleep(10)
            # 100 снимков стека в секунду flame graph в SVG
            args=['exec','-T','-u','root','search','py-spy','record','--pid','1',
                  '--duration','60','--rate','100','-o',f'/tmp/{name}.svg']
            if idle:args.append('--idle')
            command(*args)
            if process.wait()!=0:raise RuntimeError(name)
        copy(f'/tmp/{name}.svg',RESULTS/f'{name}.svg')
        copy(f'/tmp/{name}.json',RESULTS/f'{name}.json')
        print('DONE',name,flush=True)
    # Сводная таблица всех 15 замеров в CSV
    with (RESULTS/'summary.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(summary[0]))
        writer.writeheader();writer.writerows(summary)
    metadata['finished_utc']=datetime.now(timezone.utc).isoformat()
    (RESULTS/'environment.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2))

if __name__=='__main__':main()

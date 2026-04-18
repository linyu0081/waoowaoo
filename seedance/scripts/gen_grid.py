#!/usr/bin/env python3
"""批量上传参考图并提交 CLIP-02 3×3 宫格分镜图生成任务"""
import subprocess
import json
import sys
import time

ZENSTUDIO_API_KEY = "zmcp_3b526814a6df4339838fa7b927fa7bc4"
BASE_DIR = "/data/workspace/waoowaoo/seedance/projects/零号频率/assets/images"

# CLIP-02 涉及的参考图
REF_IMAGES = [
    f"{BASE_DIR}/char-叶烬-全武装.png",       # @图片1 叶烬（六翼全武装形态）
    f"{BASE_DIR}/char-灵曦-base.png",         # @图片2 灵曦（基础形态）
    f"{BASE_DIR}/char-米迦勒持有者.png",      # @图片3 米迦勒持有者
    f"{BASE_DIR}/char-天使护卫.png",          # @图片4 天使护卫
    f"{BASE_DIR}/loc-六芒星祭坛.png",         # @图片5 六芒星祭坛
]

def run_cmd(cmd):
    """运行命令并返回输出"""
    env = {"ZENSTUDIO_API_KEY": ZENSTUDIO_API_KEY, "PATH": "/data/home/allenyulin/.workbuddy/binaries/node/versions/20.18.0/bin:/usr/local/bin:/usr/bin:/bin", "HOME": "/data/home/allenyulin"}
    result = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    return result.stdout.decode('utf-8', errors='replace') + result.stderr.decode('utf-8', errors='replace')

def extract_json(output):
    """从输出中提取 JSON 对象"""
    lines = output.split('\n')
    json_lines = []
    in_json = False
    brace_count = 0
    for line in lines:
        if not in_json and line.strip().startswith('{'):
            in_json = True
        if in_json:
            json_lines.append(line)
            brace_count += line.count('{') - line.count('}')
            if brace_count <= 0:
                break
    if json_lines:
        try:
            return json.loads('\n'.join(json_lines))
        except:
            pass
    return None

def upload_image(path):
    """上传图片并返回 CDN URL"""
    print("  上传: %s..." % path.split('/')[-1], flush=True)
    output = run_cmd('zencli upload "%s" -o json' % path)
    data = extract_json(output)
    if data and 'url' in data:
        url = data['url']
        print("  OK: %s..." % url[:80], flush=True)
        return url
    else:
        print("  FAIL: %s" % output[:200], flush=True)
        return None

def main():
    print("=" * 60)
    print("CLIP-02 3x3 宫格分镜图生成")
    print("=" * 60)

    # Step 1: 上传参考图
    print("\nStep 1: 上传参考图...")
    urls = []
    for img in REF_IMAGES:
        url = upload_image(img)
        if url:
            urls.append(url)
        else:
            print("上传失败，退出")
            sys.exit(1)

    print("\n全部上传成功，共 %d 张" % len(urls))

    # Step 2: 构建提示词
    prompt = (
        "生成一张3×3宫格分镜图，虚幻引擎5级照片级写实渲染，写实CGI电影质感。"
        "保持与参考图片美术风格一致。"
        "角色参考：@图片1 是叶烬（黑发，破旧夹克，三对黑灰色羽翼，头顶碎裂光环），"
"@图片2 是灵曦（银白长发，白色丝绸金纹华服，金色蕾丝项链，基础形态），"
        "@图片3 是米迦勒持有者（壮硕男子，赤金色天使战甲，炎剑），"
        "@图片4 是天使护卫（白银战甲），"
        "@图片5 是六芒星祭坛场景参考。"
        "按从左到右、从上到下顺序，每格内容如下："
        "格1：平视中景，壮硕男子穿赤金色天使战甲猛然抬头，眼神警觉，"
        "背景浮空巡逻舰警报灯闪烁，一架废土飞行器从远处高速冲入，黄昏夜色交界。"
        "格2：仰拍全景，废土飞行器在高空爆炸解体，叶烬从座舱跳出，"
        "碎片烟雾中展开三对黑灰色羽翼，头顶碎裂光环亮起，黄昏爆炸光。"
        "格3：仰拍中景，叶烬穿破旧夹克六翼展开落地祭坛中央，"
        "冲击波从脚下炸开，四名白银战甲护卫被气浪掀飞，背景两座高塔爆炸炸裂。"
        "格4：平视中景，叶烬穿破旧夹克站在灵曦面前，"
        "灵曦眼睛闭着身后六翼虚影扭曲，叶烬面带漫不经心表情。"
        "格5：近景，叶烬右手按上灵曦额头圣冠，九颗晶体同时碎裂，"
        "背景炽天使虚影痉挛崩解，爆裂光效。"
        "格6：近景，灵曦眼睛猛然睁开，冰蓝色瞳孔里金色六芒星纹路闪烁，"
        "表情从空白到困惑。"
        "格7：平视中景，叶烬单手把灵曦从光柱上扛下来，"
        "灵曦挣扎，叶烬面带痞气笑容。"
        "格8：近景，灵曦挣扎着愤怒喊话，"
        "眼中金色六芒星纹路闪烁，表情愤怒。"
        "格9：近景，叶烬面带漫不经心表情说话，"
        "背景赤金色炎剑火焰亮起。"
        "要求：叶烬外貌服饰在各格完全一致（黑发破旧夹克六翼），"
        "灵曦外貌完全一致（银白长发白色礼服），"
        "每格之间用细白线分隔，每格画面完整，电影级画质，"
        "黄昏到夜晚的光线过渡贯穿全组，禁止输出任何文字标签数字编号。"
        "请保持画风与参考图一致，虚幻引擎5级照片级写实渲染，写实CGI级特写，"
        "所有视角均呈现出统一的高保真CGI纹理和精致的技术光影效果。"
    )

    # Step 3: 提交生图任务
    input_images = ",".join(urls)
    cmd = (
        'zencli generate image '
        '--model 314 '
        '--aspect-ratio "1:1" '
        '--resolution 1 '
        '--input-images "%s" '
        '--name "CLIP-02-grid-3x3" '
        "--prompt '%s' "
        '-o json'
    ) % (input_images, prompt)

    print("\nStep 2: 提交生图任务...")
    print("  模型: 314 (贝宝2)")
    print("  比例: 1:1")
    print("  分辨率: 2K")
    print("  参考图: %d 张" % len(urls))

    output = run_cmd(cmd)
    print("\n  原始输出:\n%s" % output[:600])

    data = extract_json(output)
    if data:
        task_id = None
        if 'task_ids' in data:
            task_id = data['task_ids'][0]
        elif 'task_id' in data:
            task_id = data['task_id']

        if task_id:
            print("\n任务已提交！task_id: %s" % task_id)

            # Step 4: 轮询
            print("\nStep 3: 等待 15 秒后开始轮询...")
            time.sleep(15)

            for attempt in range(10):
                print("\n  轮询第 %d 次..." % (attempt + 1), flush=True)
                poll_output = run_cmd('zencli generate task %s -o json' % task_id)
                poll_data = extract_json(poll_output)

                if poll_data:
                    state_desc = poll_data.get('state_desc', '')
                    print("  状态: %s" % state_desc)

                    if '成功' in state_desc:
                        assets = poll_data.get('output_assets', [])
                        if assets:
                            asset_id = assets[0].get('asset_id', '')
                            print("\n生成成功！asset_id: %s" % asset_id)

                            out_dir = "/data/workspace/waoowaoo/seedance/projects/零号频率/outputs/ep01/images"
                            dl_output = run_cmd('zencli download %s -d "%s" -n "clip-02-grid-3x3.png"' % (asset_id, out_dir))
                            print("\nStep 4: 下载结果:\n%s" % dl_output[:300])
                            print("\n完成！文件: %s/clip-02-grid-3x3.png" % out_dir)
                            return
                    elif '失败' in state_desc:
                        print("\n生成失败: %s" % state_desc)
                        return
                else:
                    print("  无法解析: %s" % poll_output[:200])

                time.sleep(20)

            print("\n轮询超时，请手动查询: zencli generate task %s -o json" % task_id)
        else:
            print("\n未找到 task_id")
    else:
        print("\n提交失败")
        print("  输出:\n%s" % output)

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
零号频率 EP01 - 批量生成角色和场景参考图
使用 zencli (zenstudio-cli) 调用贝宝2 (model 314) 生图
"""

import json
import subprocess
import time
import os
import sys

ZENCLI = "/data/home/allenyulin/.workbuddy/binaries/node/versions/20.18.0/bin/zencli"
BASE_DIR = "/data/workspace/waoowaoo/seedance/projects/零号频率"
IMAGES_DIR = os.path.join(BASE_DIR, "assets/images")
ART_STYLE_SUFFIX = ", 虚幻引擎5级照片级写实渲染，写实CGI电影质感，精致技术光影效果"
CHAR_COMPOSITION = "角色设定图，白色背景，左半部分面部特写头肩半身，右半部分全身正面视图、侧面视图、背面视图三视图并排，16:9横版构图"

POLL_INTERVAL = 12  # seconds between polls
MAX_POLLS = 60      # max polls before giving up

os.makedirs(IMAGES_DIR, exist_ok=True)

def run_zencli(args):
    """Run zencli command and return parsed JSON output"""
    cmd = [ZENCLI] + args + ["-o", "json"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        print(f"  ERROR: {result.stdout} {result.stderr}")
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"  Failed to parse JSON: {result.stdout[:200]}")
        return None

def generate_image(prompt, name, aspect_ratio="16:9"):
    """Submit image generation task"""
    print(f"  Submitting: {name}")
    result = run_zencli([
        "generate", "image",
        "--prompt", prompt,
        "--model", "314",
        "--aspect-ratio", aspect_ratio,
        "--name", name
    ])
    if result and "task_id" in result:
        return result["task_id"]
    elif result and "data" in result and "task_id" in result.get("data", {}):
        return result["data"]["task_id"]
    print(f"  Failed to get task_id for {name}. Response: {result}")
    return None

def poll_task(task_id):
    """Poll task until completion"""
    for i in range(MAX_POLLS):
        result = run_zencli(["generate", "task", task_id])
        if result is None:
            time.sleep(POLL_INTERVAL)
            continue

        status = None
        data = result if isinstance(result, dict) else {}
        if "status" in data:
            status = data["status"]
        elif "data" in data and "status" in data.get("data", {}):
            status = data["data"]["status"]

        if status == "completed" or status == "success":
            # Extract image URL
            url = None
            if "url" in data:
                url = data["url"]
            elif "data" in data:
                d = data["data"]
                if "url" in d:
                    url = d["url"]
                elif "images" in d and len(d["images"]) > 0:
                    url = d["images"][0].get("url")
                elif "result" in d:
                    r = d["result"]
                    if isinstance(r, dict):
                        url = r.get("url") or (r.get("images", [{}])[0].get("url") if r.get("images") else None)
            return {"status": "completed", "url": url, "raw": data}
        elif status == "failed" or status == "error":
            return {"status": "failed", "raw": data}

        print(f"    Poll {i+1}: status={status}, waiting {POLL_INTERVAL}s...")
        time.sleep(POLL_INTERVAL)

    return {"status": "timeout"}

def download_image(url, output_path):
    """Download image using zencli"""
    if not url:
        print(f"  No URL to download for {output_path}")
        return False
    cmd = [ZENCLI, "download", "--url", url, "-d", os.path.dirname(output_path), "-n", os.path.basename(output_path)]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode == 0 and os.path.exists(output_path):
        print(f"  Downloaded: {output_path}")
        return True
    print(f"  Download failed: {result.stdout} {result.stderr}")
    return False


# ===================== CHARACTER PROMPTS =====================

CHARACTER_TASKS = [
    {
        "name": "char-叶烬",
        "prompt": "叶烬，男性，约二十五岁，棱角分明的面庞带着几分痞气，剑眉斜飞入鬓，眼窝微陷，高挺的鼻梁微微弯曲似曾受伤，薄唇紧抿带着漫不经心的弧度。灰黑色短发凌乱蓬松向后梳去，发丝间夹杂几缕暗银。身形高挑精瘦，穿着破旧的黑色军用夹克，拉链半开露出暗灰色内衬，下身是膝盖磨破的黑色工装裤，腰间系着旧皮带挂着几个金属扣件。左手戴着黑色皮质手套遮住手背。脚蹬一双沾满尘土的黑色战术靴，鞋底厚重，靴面有多处划痕。" + CHAR_COMPOSITION + ART_STYLE_SUFFIX,
    },
    {
        "name": "char-灵曦",
        "prompt": "灵曦，女性，约十九岁，精致的鹅蛋脸如玉雕琢，眉如远山含黛，眉心隐有金色六芒纹印。琼鼻小巧挺秀，唇形如花瓣微抿。银白色长发如瀑倾泻及腰，发质柔顺如丝，被频率场扬起飘散。身形纤细高挑，穿着圣女全套仪式礼服——白色丝绸长袍拖曳至地，外覆金纹圣甲，胸前镶嵌一枚发光的频率核心。头戴细金链圣冠，冠上镶嵌九颗频率共振晶体闪烁白金光芒。赤足踩在凝固的光上，脚踝处有金色光环缠绕。" + CHAR_COMPOSITION + ART_STYLE_SUFFIX,
    },
    {
        "name": "char-大祭司光耀",
        "prompt": "大祭司光耀，男性，约六十岁，面容清癯威严，额头宽阔布满智慧纹路，眉毛花白却依然浓密，眉骨高耸，双眼深陷眼窝却目光如电。鼻梁挺直如刀削，法令纹深刻，薄唇紧抿透出不容置疑的威严。银白短发一丝不苟向后梳理，发际线微退。身形清瘦挺拔，穿着纯白丝绸祭司长袍拖曳至地，袍身绣满金色圣纹，领口金线镶边。胸前悬挂金色六芒星圣徽。脚穿白色软皮礼靴，靴面绣有金色几何图案。" + CHAR_COMPOSITION + ART_STYLE_SUFFIX,
    },
    {
        "name": "char-米迦勒持有者",
        "prompt": "米迦勒持有者，男性，约三十岁，面容刚毅如铸铁，剑眉如刀横贯额际，眼角有细纹显示经历，高挺的鼻梁略带弧度，下颌方正有力，颧骨突出。深棕色短发利落剪裁，贴合头型。体格健硕魁梧如军人，全身覆盖赤金色天使战甲，甲胄表面流动着火焰般的频率纹路。六翼从背后展开，每片翼面都覆盖着流动的炎焰纹路，翼展超过四米。右手握着一柄炎剑，剑身由纯粹频率能量凝聚，赤金火焰缭绕剑刃。脚踏赤金色战靴，靴面有熔岩纹路流转。" + CHAR_COMPOSITION + ART_STYLE_SUFFIX,
    },
    {
        "name": "char-彼列持有者",
        "prompt": "彼列持有者，男性，双面人形态，身形高瘦。左半脸是年轻英俊的人类面孔，眉目清秀如贵公子，眼角微微上挑透出温柔笑意，肤质光滑，嘴角噙着诚恳的微笑。右半脸是完全异化的恶魔相貌，灰白色皮肤上刻满裂纹如干涸的泥地，眼窝深陷，瞳孔是竖直的黄色蛇瞳，嘴角的笑容在这半边脸上扭曲成令人不适的弧度。两种面孔在鼻梁正中分界。黑发左半边梳理整齐，右半边凌乱如荒草。穿着暗色有机质甲胄，表面流动着不规则的血红色纹路像活物的血管。脚踩暗灰色高筒靴，靴面有裂纹纹路。" + CHAR_COMPOSITION + ART_STYLE_SUFFIX,
    },
    {
        "name": "char-安度西亚斯持有者",
        "prompt": "安度西亚斯持有者，男性，约三十五岁，半武装状态。头部被类似独角兽的角质头盔完全覆盖，头盔呈暗灰色带金属光泽，额头正中一根螺旋长角向前伸出约三十厘米，角身有频率纹路盘绕。下颌处有通气孔状的开口。身形壮硕魁梧如山岳，胸肌和肩肌撑起暗灰色战斗服，手臂粗壮有力。双手各握一根共振弦——由频率能量凝成的扭曲金属鞭，嗡嗡震颤。脚穿暗灰色厚底战靴，靴身粗重稳固。" + CHAR_COMPOSITION + ART_STYLE_SUFFIX,
    },
    {
        "name": "char-梦魇持有者",
        "prompt": "梦魇持有者，性别不明，体型瘦小蜷缩。全身覆盖暗色鳞片，鳞片细密如蛇皮，在暗处几乎与阴影融为一体。面部特征模糊，只有一双发出淡紫色荧光的眼睛清晰可见，瞳孔如垂直的裂缝。四肢纤细修长，指尖是暗紫色的利爪。整体轮廓似蹲伏的暗影，边缘模糊不清仿佛随时会融化进黑暗。脚部也被鳞片覆盖，足爪紧贴地面如同暗影的延伸。" + CHAR_COMPOSITION + ART_STYLE_SUFFIX,
    },
    {
        "name": "char-嫉妒冠持有者",
        "prompt": "嫉妒冠持有者，性别不明，身形朦胧如镜中幻影。全身表面如流动的镜面，反射出扭曲的周围景象，镜面下无数张不同的人脸在流动浮现又消失——那些曾被镜像掠夺能力复制过的人的残影。身体轮廓时而清晰时而模糊，如同不稳定的全息投影。穿着暗色长袍，袍面同样呈镜面质感，幽绿色的光芒在袍角游走。脚下踩着镜面质感的靴子，靴面流动着被复制面孔的残影。" + CHAR_COMPOSITION + ART_STYLE_SUFFIX,
    },
    {
        "name": "char-天使护卫",
        "prompt": "天使护卫，男性，约三十岁，面容普通但神情严肃，眉目端正，穿着白银色制式天使战甲，甲胄覆盖躯干和四肢，胸甲上有天使徽记。一对白色翅翼从背后展开，翼展约三米。手持频率能量凝成的光矛。脚穿银白色战靴，靴面有简洁的频率纹路。" + CHAR_COMPOSITION + ART_STYLE_SUFFIX,
    },
    {
        "name": "char-技术人员",
        "prompt": "技术人员，男性，约三十岁，面容普通，戴着一副银边眼镜，神情专注。穿着白灰相间的教团技术制服，制服上有简单的频率监测徽章。手持平板状的频率监测设备。脚穿灰色软底工作鞋。" + CHAR_COMPOSITION + ART_STYLE_SUFFIX,
    },
    # S-tier sub-appearances
    {
        "name": "char-叶烬-半武装",
        "prompt": "叶烬，男性，约二十五岁。半武装状态：暗银色铠甲从心口向外延展，覆盖躯干和四肢，左半身刻满精密几何纹路，右半身爬满有机质裂纹，两种纹路在胸口交界处闪烁暗金色光芒。三对暗灰色羽翼从背后展开，翼缘燃烧着暗焰。头顶一圈碎裂的光环发出不稳定的暗金色脉冲。左手黑手套破裂露出黑色硬质甲壳覆盖的手指，指尖是暗金利爪。脚踏暗银色战靴，靴面刻有频率纹路。" + CHAR_COMPOSITION + ART_STYLE_SUFFIX,
    },
    {
        "name": "char-叶烬-全频同步",
        "prompt": "叶烬，男性，约二十五岁。全频同步完全武装：全身覆盖暗银与暗金交织的铠甲，左半身几何纹路泛着天使系白光，右半身有机裂纹流动恶魔系暗焰，胸口交界处暗金光芒暴涨。六对暗灰色羽翼完全展开，翼展宽阔，每片羽翼边缘燃烧着黑色暗焰。碎裂光环脉冲加倍形成持续的暗金恒光。左手完全暴露，黑色硬质甲壳延伸至前臂，指尖暗金利爪，关节缝隙闪烁双频能量。脚踏全甲战靴，靴面纹路发出暗金光芒。" + CHAR_COMPOSITION + ART_STYLE_SUFFIX,
    },
    {
        "name": "char-灵曦-半降临",
        "prompt": "灵曦，女性，约十九岁。半降临状态：白金色光甲从右肩开始生长覆盖右半身，几何结构精密到每个菱形切面都严丝合缝，光甲沿锁骨蔓延至右臂、右胸、右腰。三对光翼从背后绽开——仅展开一对半，共三翼，每片光翼发出灼目白光。眉心金色六芒纹更加清晰。仪式白袍左肩处有撕裂破损。脚穿白色软底长靴，靴面沾有尘土。" + CHAR_COMPOSITION + ART_STYLE_SUFFIX,
    },
    {
        "name": "char-灵曦-完全降临",
        "prompt": "灵曦，女性，约十九岁。完全降临瞬间：三翼暴涨为六翼，纯白光翼从背后炸裂展开，几何结构精密到令人窒息，每片翼面都在发出灼目圣光。全身被白金光甲完整覆盖，甲胄造型神圣庄严。完整的炽天使光环从头顶涌出，直径五米，表面火焰文字疯狂流转。白金全甲战靴包裹双足，靴面圣纹发光。" + CHAR_COMPOSITION + ART_STYLE_SUFFIX,
    },
]

# ===================== SCENE PROMPTS =====================

SCENE_TASKS = [
    {
        "name": "scene-曙光城中央广场_黄昏",
        "prompt": "「曙光城中央广场」广角镜头俯瞰，黄昏的金光洒落在白色与金色交织的宏伟广场上。前景是几座精雕细琢的天使雕像基座一角，中景是铺满整个广场的白袍信众跪地祈祷，人群如白色海洋延伸至远方。背景正中央三十米高空悬浮着六芒星祭坛平台，六座四十层楼高的频率放大塔矗立在六个顶点，塔尖射出的白色光柱在天穹交汇成巨大的几何符阵。远处天际线上浮空圣城Sanctum的投影若隐若现，十二艘浮空巡逻舰列阵于上空。图上标注位置：A位-广场前方祭坛投影处，B位-广场左侧天使雕像旁，C位-广场右侧放大塔底座前，D位-信众人群边缘街道入口处，用醒目的白色大写字母标注在对应位置上" + ART_STYLE_SUFFIX,
    },
    {
        "name": "scene-六芒星祭坛_黄昏",
        "prompt": "「六芒星祭坛」广角镜头展现悬浮平台全貌，六芒星造型的白金平台悬浮在黄昏的天空中。前景是平台边缘精密的几何纹路和发光的边沿，中景是开阔的平台中央，六条光柱从六座放大塔射向中心交汇，交汇点凝聚成一团耀眼的白光。背景是六座四十层楼高的频率放大塔矗立在六角顶点，塔尖射出的白色光柱在更高处交汇成旋转的几何符阵。平台表面铺设着复杂的频率导引纹路，白金光芒在纹路中流动。图上标注位置：A位-祭坛正中央光柱交汇点，B位-祭坛边缘靠近放大塔处，C位-祭坛北侧护卫站位，D位-祭坛后方技术监控位，用醒目的白色大写字母标注在对应位置上" + ART_STYLE_SUFFIX,
    },
    {
        "name": "scene-曙光城主干道_夜晚",
        "prompt": "「曙光城主干道」夜景广角镜头，宽阔的柏油路面在路灯的频率净化光下泛着冷白色。前景是路边一排被烧焦车顶的教团礼宾车，中景是开阔的街道中央，地面有一道新鲜的两米长擦痕。背景左侧是白色与金色的建筑群，几何线条简洁干净，右侧每隔五十米矗立一座三米高的天使雕像。远处天空中巡逻舰的探照灯在扫动，祭坛方向有光柱闪烁。图上标注位置：A位-街道中央落地点，B位-街道左侧礼宾车旁，C位-街道右侧天使雕像前，D位-街道远端建筑入口处，用醒目的白色大写字母标注在对应位置上" + ART_STYLE_SUFFIX,
    },
    {
        "name": "scene-曙光城街巷_夜晚",
        "prompt": "「曙光城街巷」夜景下的狭窄巷道，两侧白色建筑墙壁夹道而立形成窄长通道。前景是巷口一座三米高天使雕像的基座一角，中景是狭长的巷道，两侧墙面嵌着一排频率净化路灯，路灯散发柔和白光。背景是巷道深处的转角，高架廊桥横跨巷道上方，廊桥上挂着金色横幅。地面是干净的白色石板，墙角有几处门洞可供躲藏。路灯玻璃罩内有频率能量流动。图上标注位置：A位-巷口天使雕像后方，B位-巷道中段路灯下，C位-巷道转角门洞内侧，D位-巷道尽头出口处，用醒目的白色大写字母标注在对应位置上" + ART_STYLE_SUFFIX,
    },
    {
        "name": "scene-曙光城商业街_夜晚",
        "prompt": "「曙光城商业街」夜景广角镜头，宽阔的商业街在夜色中空无一人却满地狼藉。前景是散落一地的祈祷垫、频率感应徽章和踩碎的圣光纪念品，中景是宽阔的街道，几面碎裂的教团旗帜躺在地上，旗帜上印着圣女画像。背景是两侧白金色商铺建筑，招牌熄灭，橱窗内的商品依稀可见。街道尽头有一处门洞入口，探照灯的余光偶尔从天空扫过。图上标注位置：A位-街道中央祈祷垫散落处，B位-街道左侧商铺门前，C位-街道右侧碎裂旗帜旁，D位-街道深处建筑门洞阴影处，用醒目的白色大写字母标注在对应位置上" + ART_STYLE_SUFFIX,
    },
    {
        "name": "scene-曙光城西门_夜晚",
        "prompt": "「曙光城西门」夜景广角展现城门区域，前方是高耸的城墙和关闭的城门。前景是街道边缘一栋三层建筑的墙角，中景是宽阔的城门前广场，地面有被炎剑劈开的熔融坑洞。背景是三百米高的频率屏蔽护盾从城墙顶端垂落，半透明的几何光纹编织成发光之墙，像一道巨大的光幕封锁了出口。护盾表面频率纹路密集闪烁，任何接触都会被中和。图上标注位置：A位-街道中央面向护盾处，B位-街道北侧建筑墙角处，C位-街道东侧巷口边缘，D位-街道西侧城门护盾前空地，用醒目的白色大写字母标注在对应位置上" + ART_STYLE_SUFFIX,
    },
    {
        "name": "scene-护盾节点_夜晚",
        "prompt": "「护盾节点」夜景下的护盾发生器区域，城墙内嵌的关键设施。前景是一些被战斗破坏的地面碎石和裂缝，中景是空旷的节点前方空地，地面有共振武器留下的震裂痕迹。背景是嵌入城墙的圆柱形护盾节点装置，高约十米，表面覆盖密密麻麻的频率纹路，正在发出蓝白色光芒。节点外层有已被净化之焰烧穿的防护装甲残骸。城墙高耸，护盾光幕从节点顶部延伸向天空。图上标注位置：A位-节点装置正前方空地，B位-节点左侧城墙根部，C位-节点右侧废墟碎石旁，D位-节点后方建筑废墟边缘，用醒目的白色大写字母标注在对应位置上" + ART_STYLE_SUFFIX,
    },
    {
        "name": "scene-废土带_夜晚",
        "prompt": "「废土带」夜景广角镜头，与曙光城截然不同的荒芜世界。前景是生锈的钢铁废墟和覆盖异变藤蔓的碎石，藤蔓发出病态的荧绿色光。中景是坍塌的高架桥下方可供遮蔽的空间，断裂的钢梁横七竖八。背景是废弃建筑群的轮廓，窗洞黑暗如眼眶，外墙挂着褪色的广告牌变成诡异鬼脸。青绿色雾霾弥漫，地面有频率污染留下的荧光色斑块。远处曙光城的灯光如孤岛。图上标注位置：A位-高架桥下遮蔽处，B位-断裂钢梁旁可坐处，C位-废弃建筑窗洞前空地，D位-锈蚀滑梯旁藤蔓边缘，用醒目的白色大写字母标注在对应位置上" + ART_STYLE_SUFFIX,
    },
    {
        "name": "scene-废墟塔顶_夜晚",
        "prompt": "「废墟塔顶」夜景远景，废土区中一座残破高塔的顶层。前景是塔顶边缘破碎的石栏杆和风化的装饰残件，中景是塔顶平台，地面布满裂缝和碎石，几根断裂的石柱残存。背景是远处一公里外的曙光城全景，城市灯光在夜色中如发光的孤岛，护盾的光幕清晰可见。青绿雾霾在塔下翻涌，偶有异变生物的影子掠过。塔顶视野开阔，可俯瞰整个战场。图上标注位置：A位-塔顶边缘俯瞰城市处，B位-塔顶中央残破石柱旁，C位-塔顶角落阴影遮蔽处，用醒目的白色大写字母标注在对应位置上" + ART_STYLE_SUFFIX,
    },
    {
        "name": "scene-祭坛废墟_夜晚",
        "prompt": "「祭坛废墟」夜景广角镜头，仪式中断后的六芒星祭坛残骸。前景是炸毁的频率放大塔底座残骸，金属扭曲变形，中景是碎裂的六芒星平台，裂纹如蛛网从撞击点向外辐射，六座放大塔已炸毁两座，残余四座也已停机。背景是夜空中仍在消散的频率光粒子，如金色灰烬缓缓飘落。平台表面的频率纹路已暗淡熄灭，只有零星火花闪烁。远处巡逻舰的探照灯还在搜索。图上标注位置：A位-碎裂平台中央，B位-平台边缘炸毁放大塔残骸旁，C位-平台裂缝旁可站立区域，D位-平台一角相对完整处，用醒目的白色大写字母标注在对应位置上" + ART_STYLE_SUFFIX,
    },
]


def main():
    results = {"success": [], "failed": []}

    # Phase 1: Submit all tasks
    print("=" * 60)
    print("Phase 1: Submitting all generation tasks")
    print("=" * 60)

    all_tasks = []

    # Characters
    print("\n--- Characters ---")
    for task in CHARACTER_TASKS:
        task_id = generate_image(task["prompt"], task["name"], "16:9")
        if task_id:
            all_tasks.append({"name": task["name"], "task_id": task_id, "type": "char"})
        else:
            results["failed"].append({"name": task["name"], "reason": "submit_failed"})
        time.sleep(1)  # Brief pause between submissions

    # Scenes
    print("\n--- Scenes ---")
    for task in SCENE_TASKS:
        task_id = generate_image(task["prompt"], task["name"], "16:9")
        if task_id:
            all_tasks.append({"name": task["name"], "task_id": task_id, "type": "scene"})
        else:
            results["failed"].append({"name": task["name"], "reason": "submit_failed"})
        time.sleep(1)

    print(f"\nSubmitted {len(all_tasks)} tasks, {len(results['failed'])} failed to submit")

    # Phase 2: Poll all tasks
    print("\n" + "=" * 60)
    print("Phase 2: Polling tasks for completion")
    print("=" * 60)

    for task_info in all_tasks:
        name = task_info["name"]
        task_id = task_info["task_id"]
        print(f"\nPolling: {name} (task_id: {task_id})")

        result = poll_task(task_id)
        if result["status"] == "completed":
            url = result.get("url")
            output_path = os.path.join(IMAGES_DIR, f"{name}.png")

            if url:
                if download_image(url, output_path):
                    results["success"].append({"name": name, "path": output_path})
                else:
                    # Retry download once
                    print(f"  Retrying download for {name}...")
                    time.sleep(3)
                    if download_image(url, output_path):
                        results["success"].append({"name": name, "path": output_path})
                    else:
                        results["failed"].append({"name": name, "reason": "download_failed", "url": url})
            else:
                results["failed"].append({"name": name, "reason": "no_url_in_result", "raw": str(result.get("raw", ""))[:200]})
        else:
            results["failed"].append({"name": name, "reason": result["status"]})

    # Phase 3: Retry failed tasks
    failed_submits = [f for f in results["failed"] if f["reason"] == "submit_failed"]
    if failed_submits:
        print("\n" + "=" * 60)
        print("Phase 3: Retrying failed submissions")
        print("=" * 60)
        all_task_map = {t["name"]: t for t in CHARACTER_TASKS + SCENE_TASKS}
        for fail in failed_submits:
            name = fail["name"]
            task_data = all_task_map.get(name)
            if task_data:
                print(f"\nRetrying: {name}")
                task_id = generate_image(task_data["prompt"], name, "16:9")
                if task_id:
                    result = poll_task(task_id)
                    if result["status"] == "completed" and result.get("url"):
                        output_path = os.path.join(IMAGES_DIR, f"{name}.png")
                        if download_image(result["url"], output_path):
                            results["failed"] = [f for f in results["failed"] if f["name"] != name]
                            results["success"].append({"name": name, "path": output_path})

    # Summary
    print("\n" + "=" * 60)
    print("FINAL RESULTS")
    print("=" * 60)
    print(f"\nSuccess: {len(results['success'])}/{len(CHARACTER_TASKS) + len(SCENE_TASKS)}")
    for s in results["success"]:
        print(f"  OK  {s['name']} -> {s['path']}")
    if results["failed"]:
        print(f"\nFailed: {len(results['failed'])}")
        for f in results["failed"]:
            print(f"  FAIL {f['name']}: {f['reason']}")

    # Write results to JSON
    results_path = os.path.join(BASE_DIR, "assets/generation_results.json")
    with open(results_path, "w", encoding="utf-8") as fp:
        json.dump(results, fp, ensure_ascii=False, indent=2)
    print(f"\nResults saved to: {results_path}")

    return len(results["failed"]) == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

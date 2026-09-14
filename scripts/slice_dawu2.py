"""把 二级大雾题库.pdf 按实验切图，生成 src/asserts/dawu2/{键}.jpg。

每个实验一张整图：单页实验直接渲染该页；多页实验纵向拼接后存为一张 JPG。
"""
from pathlib import Path
import subprocess
import tempfile

from PIL import Image  # type: ignore[import-not-found]  # 系统级安装，.venv 中无此包

PROJECT = Path.cwd()
PDF = PROJECT / "二级大雾题库" / "二级大雾题库.pdf"
OUT = PROJECT / "src" / "asserts" / "dawu2"
DPI = 150

# 键 → [起始页, 结束页]（物理页码）
EXPERIMENTS = {
    "Young_Modulus_Poisson": [6, 6],
    "Air_Damping": [7, 7],
    "Kater_Pendulum": [8, 8],
    "Rotational_Inertia": [9, 9],
    "Contact_Angle": [10, 10],
    "Thermal_Conductivity": [11, 11],
    "Hall_Effect": [12, 12],
    "Magnetoresistance": [13, 13],
    "Electronics_Craft": [14, 14],
    "Sensor": [15, 15],
    "Wheatstone_Bridge": [16, 17],
    "Unbalance_Bridge": [18, 19],
    "Digital_Meter": [20, 21],
    "AC_Resonance": [22, 23],
    "Dielectric_Constant": [24, 24],
    "Michelson_Interferometer": [25, 26],
    "Double_Grating": [27, 27],
    "Polarized_Light": [28, 28],
    "Ultrasonic_Grating": [29, 30],
    "Ultrasonic_Locating": [31, 31],
    "Optical_Fiber_Sensor": [32, 32],
    "Bicurvature_Lens_1": [33, 33],
    "Bicurvature_Lens_2": [34, 35],
    "FH_Experiment": [36, 36],
    "Spectrograph": [37, 37],
    "Monochromator": [38, 38],
    "Medical_Physics": [39, 40],
}


def render_page(page: int, out_prefix: Path) -> Path:
    """把 PDF 指定页渲染为 PNG，返回路径。"""
    subprocess.run(
        [
            "pdftoppm", "-png", "-r", str(DPI),
            "-f", str(page), "-l", str(page),
            str(PDF), str(out_prefix),
        ],
        check=True,
    )
    # pdftoppm 输出 <prefix>-<page>.png（页码带前导零）
    matches = list(sorted(out_prefix.parent.glob(out_prefix.name + "*.png")))
    if not matches:
        raise RuntimeError(f"页面 {page} 渲染失败")
    return matches[0]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    collapsed = {k: [e[0], e[-1]] for k, e in EXPERIMENTS.items()}

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        for key, (start, end) in collapsed.items():
            pages = list(range(start, end + 1))
            rendered = [render_page(p, tmpdir / f"pg{p}") for p in pages]
            if len(rendered) == 1:
                img = Image.open(rendered[0]).convert("RGB")
            else:
                imgs = [Image.open(p).convert("RGB") for p in rendered]
                width = max(i.width for i in imgs)
                imgs = [i.resize((width, i.height)) if i.width != width else i for i in imgs]
                height = sum(i.height for i in imgs)
                canvas = Image.new("RGB", (width, height), "white")
                y = 0
                for i in imgs:
                    canvas.paste(i, (0, y))
                    y += i.height
                img = canvas
            out_path = OUT / f"{key}.jpg"
            # 约束最大宽度（QQ 长图），保持清晰度
            img.save(out_path, "JPEG", quality=90, optimize=True)
            print(f"{key}: {len(pages)}页 -> {out_path.name} ({img.size[0]}x{img.size[1]})")

    # 校验
    reported = set(EXPERIMENTS)
    on_disk = {p.stem for p in OUT.glob("*.jpg")}
    missing = reported - on_disk
    extra = on_disk - reported
    print("\n=== 校验 ===")
    print(f"期望 {len(reported)} 张，磁盘 {len(on_disk)} 张")
    if missing:
        print("缺失:", sorted(missing))
    if extra:
        print("多余:", sorted(extra))
    if not missing and not extra:
        print("OK: 全部一一对应")


if __name__ == "__main__":
    main()
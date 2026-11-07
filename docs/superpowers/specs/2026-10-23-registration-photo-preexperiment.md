# 工业相机照片配准预实验：已批准方案的输入扩展

用户确认2026-10-22照片样本目录中两张PNG来自工业相机，可用于配准；因最终实验尚需调整芯片高度，于2026-10-23明确批准“先作为预实验”。沿用已批准的独立配准工作包、8fit/16check及人工审核流程，不重新设计状态/控制算法。

新增真实照片输入入口，不构造虚假AVI、SDK帧号或曝光时间戳，不将照片塞入旧视频资源清单。复制并核对原始PNG/hash，生成新的照片工作包；保留旧视频点位、未完成C10、旧图和全部结果。两张接近机位照片不当作两个独立芯片实验。

每张照片的新初始化四角只由图像预览粗略定位，用于导航；必须明确assistant_navigation_only/unconfirmed，不能继承旧视频H、拟合点、检查点或旧人工真值。新的8fit/16check都绑定现有420真实轮廓顶点且observed_px为null，全部pending。人工冻结拟合与检查点一次性评价语义保持不变。

工作包/图稿/核对窗口明确显示PRE-EXPERIMENT/预实验，标识final_experiment_calibration_approved=false、transfer_to_old_videos_verified=false及final_relative_height_fixed=false。即使后续预实验点位全部通过，不能自动升级为最终标定。最终高度/装配/光学状态确定后另建标定版本。

只新增照片适配器、CLI分支、少量来源显示及预实验标识，复用现有ImageCanvas、point_catalog、load_workspace/build_report、CRLF启动文件。原运行地图、GUI主程序、U-Net、五状态、闭环、STM32/AM、第三章及论文Fig.2-4均不改；不commit/push。

交付两张原尺寸照片、各自初始420轮廓叠加和点位导航、来源manifest、CSV/JSON、Windows双击入口。无新人工点位时不输出数值精度。先验照片接口测试RED→GREEN，照片与旧视频回归、全量软件测试及来源hash检查；最终PDF/SVG/600dpi PNG逐图QA。

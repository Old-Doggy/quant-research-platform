"""Data workspace implementation and route adapter for the local workbench."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, TypeVar

T = TypeVar("T")

_DATA_GLOBALS = (
    "DEFAULT_DATA_ROOT", "PUBLIC_MODE", "SAMPLE_ROOT", "DataCenter",
    "DataWorkflowStep", "RegistrationConfirmationRequired", "_data_registry_root",
    "_data_source_kind", "_data_workflow_state", "_render_data_workflow_stepper",
    "_reset_data_workflow_inputs", "_set_data_workflow_state", "_stage_uploaded_data",
    "build_data_quality_report", "build_dataset_manifest", "build_market_summary",
    "cached_local_symbol", "hashlib", "list_local_symbols", "next_data_workflow",
    "read_market_file", "render_import_preview", "show_safe_error",
    "st", "pd", "Path",
)


def render_data_workspace(route_state: Any, *, render_body: Callable[[Any], T]) -> T:
    """Render the data workspace only when the router selected data."""
    if getattr(route_state, "active_workspace", None) != "data":
        raise ValueError("data workspace requires the data route")
    return render_body(route_state)


def render_data_workspace_body(route_state: Any, *, app_globals: Mapping[str, Any]) -> None:
    """Render the data workflow using dependencies supplied by the local app."""
    module_globals = globals()
    from .workspace_dependencies import bind_workspace_dependencies
    bind_workspace_dependencies(module_globals, app_globals, _DATA_GLOBALS)

    """Render the data workflow while keeping existing analysis views available."""
    st.title("数据中心 / Data Center")
    st.caption("统一完成导入、预览、质量检查和版本登记；数据只在本地研究模式中使用。")

    with st.expander("数据来源与设置", expanded=False):
        options = ["合成示例", "文件导入"] if PUBLIC_MODE else ["合成示例", "文件导入", "本地行情"]
        data_source = st.selectbox("数据来源", options, key="analysis_source", filter_mode=None)
        data_root = str(DEFAULT_DATA_ROOT)
        adjusted = "qfq"
        symbols: list[str] = []
        if data_source == "本地行情":
            data_root = st.text_input("本地数据目录", data_root, key="analysis_data_root")
            adjusted = st.selectbox("价格口径", ["qfq", "hfq", "raw"], index=0, key="analysis_adjusted", filter_mode=None)
            symbols = list_local_symbols(data_root, adjusted)

    source_kind = _data_source_kind(data_source)
    state = _data_workflow_state()
    frame = st.session_state.get("data_workflow_frame")
    uploaded = None
    selected_symbol = None
    if data_source == "合成示例":
        frame = read_market_file(SAMPLE_ROOT / "quant_demo_multi_symbol.csv")
        dataset_id = "seeded_demo"
    elif data_source == "文件导入":
        # The uploader is the only source of truth for this branch. A prior
        # source's frame must not appear while the user is choosing a file.
        frame = None
        dataset_id = st.text_input("数据集 ID", st.session_state.get("data_workflow_dataset_id", "my_dataset"), key="data_workflow_dataset_id")
    else:
        dataset_id = "local_market"
        if symbols:
            selected_symbol = st.selectbox("本地股票", symbols, key="analysis_symbol", filter_mode=None)
            frame = cached_local_symbol(data_root, selected_symbol, adjusted)

    workflow_identity = (
        source_kind,
        dataset_id,
        str(Path(data_root).resolve()) if data_source == "本地行情" else None,
        adjusted if data_source == "本地行情" else None,
        selected_symbol,
    )
    previous_identity = st.session_state.get("data_workflow_identity")
    if previous_identity is not None and previous_identity != workflow_identity:
        # A source, dataset, symbol or price-basis switch invalidates the old
        # preview, quality result and staged upload.
        state = _reset_data_workflow_inputs()
    elif state.source_kind not in {None, source_kind}:
        state = _reset_data_workflow_inputs()
    st.session_state["data_workflow_identity"] = workflow_identity

    _render_data_workflow_stepper(state)
    steps = ["① 导入与预览", "② 质量检查", "③ 数据版本", "④ 进入研究"]
    current_step = list(DataWorkflowStep).index(state.step)
    import_tab, quality_tab, version_tab, research_tab = st.tabs(steps, default=steps[current_step],
        key=f'data_workflow_tabs_{state.step.value}')

    with import_tab:
        st.subheader("导入数据 / Import data")
        if data_source == "文件导入":
            uploaded = st.file_uploader(
                "选择 CSV、Excel 或 Parquet 文件",
                type=["csv", "xlsx", "xls", "parquet", "pq"],
                key="analysis_upload",
            )
            if uploaded is None:
                st.info("选择文件后，先完成字段映射和预览；确认预览后才会进入质量检查。")
            else:
                upload_fingerprint = hashlib.sha256(uploaded.getvalue()).hexdigest()
                previous_upload = st.session_state.get("data_workflow_upload_fingerprint")
                if previous_upload is not None and previous_upload != upload_fingerprint:
                    state = _reset_data_workflow_inputs()
                st.session_state["data_workflow_upload_fingerprint"] = upload_fingerprint
                preview_frame = render_import_preview(uploaded, key="data_workflow")
                if preview_frame is not None:
                    frame = preview_frame
                    st.session_state["data_workflow_frame"] = frame
                    if state.step is DataWorkflowStep.IMPORT:
                        if st.button("确认预览，进入质量检查", type="primary", key="confirm_data_preview"):
                            staged = _stage_uploaded_data(uploaded, dataset_id)
                            st.session_state["data_workflow_staged_path"] = str(staged)
                            state = next_data_workflow(
                                state,
                                source_kind=source_kind,
                                dataset_id=dataset_id,
                                rows=int(len(frame)),
                                symbols=int(frame["symbol"].nunique()) if "symbol" in frame else 0,
                                preview_ready=True,
                            )
                            _set_data_workflow_state(state)
                            st.rerun()
        else:
            if frame is None or frame.empty:
                st.warning("当前来源没有可用数据，请检查本地数据目录。")
            else:
                summary = build_market_summary(frame)
                st.success(f"已选择 {data_source} · {summary['rows']:,} 条记录 · {summary['symbols']:,} 个标的")
                st.dataframe(frame[[column for column in ("symbol", "trade_date", "open", "high", "low", "close") if column in frame]].head(10), width="stretch", hide_index=True)
                if state.step is DataWorkflowStep.IMPORT and st.button("使用当前数据，进入质量检查", type="primary", key="confirm_builtin_data"):
                    state = next_data_workflow(
                        state,
                        source_kind=source_kind,
                        dataset_id=dataset_id,
                        rows=int(len(frame)),
                        symbols=int(frame["symbol"].nunique()) if "symbol" in frame else 0,
                        preview_ready=True,
                    )
                    st.session_state["data_workflow_frame"] = frame
                    _set_data_workflow_state(state)
                    st.rerun()

    with quality_tab:
        st.subheader("质量检查 / Quality gate")
        if frame is None or frame.empty:
            st.info("请先在“导入与预览”完成数据确认。")
        else:
            quality = build_data_quality_report(frame)
            metric_columns = st.columns(4)
            metric_columns[0].metric("记录数", f"{len(frame):,}")
            metric_columns[1].metric("标的数", f"{frame['symbol'].nunique():,}" if "symbol" in frame else "0")
            metric_columns[2].metric("质量状态", quality["status"])
            metric_columns[3].metric("重复记录", str(quality.get("duplicate_key_rows", 0)))
            if {'symbol', 'trade_date'}.issubset(frame.columns):
                from .research_charts import build_coverage_chart, CHART_CONFIG
                st.plotly_chart(build_coverage_chart(frame), width='stretch',
                    key='data_coverage', config=CHART_CONFIG)
                st.caption('每格为当月已记录日期数 · 按代码展示前20个标的')
            quality_table = pd.DataFrame([
                {"检查项": "缺失必需字段", "异常数量": len(quality.get("missing_columns", [])), "详情": ", ".join(quality.get("missing_columns", [])) or "无"},
                {"检查项": "必需字段缺失值", "异常数量": quality.get("missing_required_value_rows", 0), "详情": "行"},
                {"检查项": "OHLC 逻辑异常", "异常数量": quality.get("invalid_ohlc_rows", 0), "详情": "行"},
                {"检查项": "非正收盘价", "异常数量": quality.get("non_positive_close_rows", 0), "详情": "行"},
                {"检查项": "重复日期记录", "异常数量": quality.get("duplicate_key_rows", 0), "详情": "行"},
                {"检查项": "日期顺序异常", "异常数量": quality.get("non_monotonic_rows", 0), "详情": "行"},
            ])
            st.dataframe(quality_table, width="stretch", hide_index=True)
            if quality["status"] == "通过":
                st.success("质量检查通过，可以进入数据版本步骤。")
                if state.step is DataWorkflowStep.QUALITY and st.button("确认质量，进入数据版本", type="primary", key="confirm_data_quality"):
                    _set_data_workflow_state(next_data_workflow(state, quality_status="通过"))
                    st.rerun()
            else:
                st.warning("数据需要复核，质量检查未通过前不能登记版本或进入研究。")
                if state.step is DataWorkflowStep.QUALITY:
                    _set_data_workflow_state(next_data_workflow(state, quality_status=str(quality["status"])))

    with version_tab:
        st.subheader("数据版本 / Dataset version")
        if state.step is DataWorkflowStep.IMPORT:
            st.info("先完成导入与质量检查。")
        elif state.step is DataWorkflowStep.QUALITY:
            st.info("质量检查通过后，才能登记数据版本。")
        elif state.step is DataWorkflowStep.RESEARCH:
            st.success(f"当前已选择版本：{state.dataset_id} / {state.version}")
        else:
            st.write(f"数据集：`{state.dataset_id}` · 记录：{state.rows:,} · 标的：{state.symbols:,}")
            if source_kind == "file_import":
                staged_path = st.session_state.get("data_workflow_staged_path")
                if not staged_path or not Path(staged_path).is_file():
                    st.warning("上传文件尚未在本地暂存，请返回导入页重新确认预览。")
                else:
                    center = DataCenter(_data_registry_root())
                    try:
                        preview = center.preview_import(staged_path, dataset_id=state.dataset_id or "my_dataset")
                        st.dataframe(pd.DataFrame([{
                            "版本状态": preview.get("status", "不可用"),
                            "建议版本": preview.get("proposed_version", "--"),
                            "历史版本": ", ".join(preview.get("previous_versions", [])) or "无",
                        }]), width="stretch", hide_index=True)
                        st.caption("版本登记只保存元数据和内容指纹，不把源文件复制到公开包。")
                        if preview.get("can_import") and st.button("登记此数据版本", type="primary", key="register_data_version"):
                            manifest = build_dataset_manifest(
                                frame,
                                dataset_id=state.dataset_id or "my_dataset",
                                display_name=state.dataset_id or "Imported dataset",
                                source_kind="user_import",
                                license_note="用户导入数据，仅供本机研究使用",
                            )
                            try:
                                result = center.register_import(staged_path, manifest, confirm=True)
                                _set_data_workflow_state(next_data_workflow(state, version=result.proposed_version))
                                st.success(f"已登记数据版本：{result.proposed_version}")
                                st.rerun()
                            except RegistrationConfirmationRequired as exc:
                                st.error(str(exc))
                    except Exception as exc:
                        show_safe_error(exc, operation="data_version")
            else:
                if st.button("确认使用版本 v001", type="primary", key="confirm_builtin_version"):
                    _set_data_workflow_state(next_data_workflow(state, version="v001"))
                    st.rerun()

    with research_tab:
        st.subheader("进入研究 / Research")
        if state.can_research:
            st.success(f"数据已就绪：{state.dataset_id} / {state.version}")
            st.write("设为当前研究数据后，看盘、因子、策略和组合工作区会使用这个版本。原始文件不进入公开包。")
            if st.button("设为当前研究数据", type="primary", key="activate_research_dataset"):
                from .research_dataset import activate_dataset
                activate_dataset(st.session_state, frame, dataset_id=state.dataset_id,
                    version=state.version, source_kind=source_kind,
                    price_basis=adjusted if source_kind == 'local_market' else 'unspecified' if source_kind == 'file_import' else 'synthetic')
                st.success("已应用。现在可从侧栏进入研究工作区。")
        else:
            st.info("完成导入、质量检查和数据版本登记后，这里会显示可进入研究的状态。")
    if frame is not None and not frame.empty:
        from .research_dataset import record_context
        record_context(st.session_state, 'data', frame, source_kind=source_kind,
            price_basis=adjusted if source_kind == 'local_market' else 'synthetic' if source_kind == 'synthetic' else 'unspecified')
        st.session_state['_actual_context_data']['dataset_id'] = dataset_id
        st.session_state['_actual_context_data'].update(
            version=state.version if state.can_research else '未登记', ready=state.can_research)
    else:
        st.session_state.pop('_actual_context_data', None)

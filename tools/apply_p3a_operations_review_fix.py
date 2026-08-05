from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "lanzou_update_push_api_server" / "control_ui" / "assets" / "operations.js"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"missing operations.js anchor: {label}")
    return text.replace(old, new, 1)


def main() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "const required = Boolean(data?.token_required || data?.admin_token_required || data?.configured);",
        "const required = Boolean(data?.token_configured || data?.token_required || data?.admin_token_required || data?.configured);",
        "security token status",
    )
    text = replace_once(
        text,
        """    if (!result.ok) {
      setText('repairStateResult', `修复失败：${result.error.message}`);
      showToast(`状态文件修复失败：${result.error.message}`, 'error');
      return;
    }
    setText('repairStateResult', JSON.stringify(result.data, null, 2));""",
        """    const repairError = !result.ok
      ? result.error.message
      : (result.data?.ok === false ? (result.data.error || '修复接口返回失败') : '');
    if (repairError) {
      setText('repairStateResult', `修复失败：${repairError}`);
      showToast(`状态文件修复失败：${repairError}`, 'error');
      return;
    }
    setText('repairStateResult', JSON.stringify(result.data, null, 2));""",
        "repair response status",
    )
    text = replace_once(
        text,
        """    if (!result.ok) {
      showToast(`配置回滚失败：${result.error.message}`, 'error');
      return;
    }
    showToast(kind === 'main' ? '主接口配置已回滚，重启服务后生效' : '蓝奏配置已回滚并刷新运行态', 'success');""",
        """    const rollbackError = !result.ok
      ? result.error.message
      : (result.data?.ok === false ? (result.data.error || '回滚接口返回失败') : '');
    if (rollbackError) {
      showToast(`配置回滚失败：${rollbackError}`, 'error');
      return;
    }
    showToast(kind === 'main' ? '主接口配置已回滚，重启服务后生效' : '蓝奏配置已回滚并刷新运行态', 'success');""",
        "rollback response status",
    )
    text = replace_once(
        text,
        """    if (!result.ok) {
      showToast(`服务重启安排失败：${result.error.message}`, 'error');
      return;
    }
    showToast('已安排 LOLDataSystem 重启，页面连接会短暂中断', 'success');""",
        """    const restartError = !result.ok
      ? result.error.message
      : (result.data?.ok === false ? (result.data.error || '重启接口返回失败') : '');
    if (restartError) {
      showToast(`服务重启安排失败：${restartError}`, 'error');
      return;
    }
    showToast('已安排 LOLDataSystem 重启，页面连接会短暂中断', 'success');""",
        "restart response status",
    )
    SCRIPT.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()

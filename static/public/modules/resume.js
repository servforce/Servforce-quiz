export function createPublicResumeModule() {
  return {
          async uploadResume() {
            const file = this.$refs.resumeFile?.files?.[0];
            if (!file) {
              this.error = "请先选择简历文件";
              return;
            }
            const form = new FormData();
            form.append("file", file);
            const result = await this.api(`/api/public/resume/upload?token=${encodeURIComponent(this.route.token)}`, {
              method: "POST",
              body: form,
            });
            history.replaceState({}, "", result.redirect);
            await this.syncRoute(result.redirect);
          },
  };
}

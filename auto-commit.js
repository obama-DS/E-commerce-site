const chokidar = require("chokidar");
const { exec } = require("child_process");

let busy = false;

console.log("Watching...");

const watcher = chokidar.watch(".", {
  ignoreInitial: true,
  ignored: [
    /(^|[\/\\])\.git/,
    /(^|[\/\\])node_modules/,
    /(^|[\/\\])\.venv/,
    /(^|[\/\\])\.venv-1/,
    /(^|[\/\\])__pycache__/,
  ],
});

watcher.on("change", (path) => {
  if (!/\.(py|html|css|js)$/.test(path)) return;
  if (busy) return;

  busy = true;

  console.log(`📄 Changed: ${path}`);

  exec(
    `git add . && git commit -m "Auto: ${path} ${new Date().toLocaleString()}" && git push`,
    (error, stdout, stderr) => {
      if (stdout) console.log(stdout);
      if (stderr) console.log(stderr);
      if (error) console.log(error.message);

      // Wait a moment before allowing another commit
      setTimeout(() => {
        busy = false;
      }, 1500);
    }
  );
});

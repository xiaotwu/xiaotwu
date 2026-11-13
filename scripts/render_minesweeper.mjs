import { pathToFileURL } from "node:url";

let source = "";
for await (const chunk of process.stdin) source += chunk;
const levels = JSON.parse(source);
const names = ["NONE", "FIRST_QUARTILE", "SECOND_QUARTILE", "THIRD_QUARTILE", "FOURTH_QUARTILE"];
const contributionDays = Object.entries(levels).map(([date, level]) => ({
  date,
  contributionCount: Number(level > 0),
  contributionLevel: names[level],
}));

// Supply the same public calendar as the heatmap through the renderer's data request.
// The solver uses only whether a day has any contributions to place its mines.
globalThis.fetch = async (url) => {
  if (url !== "https://api.github.com/graphql") {
    throw new Error("Unexpected network request from the arcade renderer.");
  }
  return Response.json({
    data: {
      user: {
        contributionsCollection: {
          contributionCalendar: { weeks: [{ contributionDays }] },
        },
      },
    },
  });
};

const { ArcadeRenderer } = await import(pathToFileURL(process.argv[2]).href);
const output = {};
for (const [theme, gameTheme] of [["light", "github"], ["dark", "github-dark"]]) {
  const renderer = new ArcadeRenderer({
    game: "minesweeper",
    platform: "github",
    username: "xiaotwu",
    githubSettings: { accessToken: "local-calendar" },
    gameTheme,
    showMonthLabels: false,
    svgCallback: (svg) => { output[theme] = svg; },
  });
  await renderer.start();
}
process.stdout.write(JSON.stringify(output));

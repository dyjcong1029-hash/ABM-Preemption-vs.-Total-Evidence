options(stringsAsFactors = FALSE)

out_dir <- commandArgs(trailingOnly = TRUE)
if (length(out_dir) != 1) {
  stop("Usage: Rscript make_static_figures.R <output-dir>")
}
dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)

blue <- "#2F6690"
gold <- "#D99B2B"
grey <- "#7A7A7A"
dark <- "#25313C"
grid <- "#E4E8EB"
policy_colours <- c(
  "No Deference" = grey,
  "E-Preemption" = gold,
  "E-Total Evidence" = blue
)

open_png <- function(filename, width = 1800, height = 1100) {
  png(
    file.path(out_dir, filename),
    width = width,
    height = height,
    res = 180,
    bg = "white",
    type = "cairo-png"
  )
}

draw_panel_title <- function(title, subtitle = NULL) {
  mtext(title, side = 3, line = 2.2, adj = 0, font = 2, cex = 1.25, col = dark)
  if (!is.null(subtitle)) {
    mtext(subtitle, side = 3, line = 0.8, adj = 0, cex = 0.82, col = "#53616D")
  }
}

# Figure 1: paired policy effects on post-intervention regret.
effects <- read.csv("report_source_regret_contrasts.csv", check.names = FALSE)
effects$comparison_short <- c(
  "Preemption\nvs no deference",
  "Total evidence\nvs no deference",
  "Total evidence\nvs preemption"
)[match(
  effects$comparison,
  c(
    "E-Preemption - No Deference",
    "E-Total Evidence - No Deference",
    "E-Total Evidence - E-Preemption"
  )
)]
comparison_order <- c(
  "Preemption\nvs no deference",
  "Total evidence\nvs no deference",
  "Total evidence\nvs preemption"
)

open_png("figure_1_paired_regret_effects.png", 1900, 1050)
par(mfrow = c(1, 2), mar = c(5.4, 7.8, 5.3, 1.8), oma = c(2.3, 0, 2.0, 0), xaxs = "i")
xlim <- range(c(effects$ci_low, effects$ci_high, 0))
xlim <- xlim + c(-0.08, 0.08)
for (world in c("B-good", "B-bad")) {
  d <- effects[effects$world == world, ]
  d <- d[match(comparison_order, d$comparison_short), ]
  y <- rev(seq_len(nrow(d)))
  plot(
    NA,
    xlim = xlim,
    ylim = c(0.45, 3.55),
    xlab = "Paired difference in post-intervention regret",
    ylab = "",
    yaxt = "n",
    bty = "n",
    col.axis = dark,
    col.lab = dark
  )
  abline(v = pretty(xlim), col = grid, lwd = 1)
  abline(v = 0, col = "#8E9AA4", lty = 2, lwd = 1.5)
  segments(d$ci_low, y, d$ci_high, y, col = blue, lwd = 3)
  points(d$estimate, y, pch = 19, col = blue, cex = 1.35)
  axis(2, at = y, labels = d$comparison_short, las = 1, tick = FALSE, col.axis = dark)
  title(if (world == "B-good") "World: B is better" else "World: B is worse", col.main = dark)
}
mtext("Experiment 1: policy effects on regret", side = 3, outer = TRUE, line = 0.7, font = 2, cex = 1.35, col = dark)
mtext("Negative values favor the first-named policy; bars are 95% paired bootstrap intervals.", side = 1, outer = TRUE, line = 0.5, cex = 0.82, col = "#53616D")
dev.off()

# Figure 2: learning trajectories after evidence is shared at tick 25.
paths <- read.csv("trajectory_chart_data.csv", check.names = FALSE)
open_png("figure_2_learning_trajectories.png", 1900, 1050)
par(mfrow = c(1, 2), mar = c(5.3, 5.4, 5.4, 1.5), oma = c(4.4, 0.8, 2.0, 0))
for (world in c("B-good", "B-bad")) {
  d_world <- paths[paths$world == world, ]
  plot(
    NA,
    xlim = range(d_world$ticks),
    ylim = c(0, 1),
    xlab = "Tick",
    ylab = "Share of student choices that are correct",
    bty = "n",
    col.axis = dark,
    col.lab = dark
  )
  abline(h = seq(0, 1, 0.2), col = grid, lwd = 1)
  abline(v = 25, col = "#8E9AA4", lty = 2, lwd = 1.5)
  for (policy in names(policy_colours)) {
    d <- d_world[d_world$policy == policy, ]
    d <- d[order(d$ticks), ]
    polygon(
      c(d$ticks, rev(d$ticks)),
      c(d$correct_ci_low, rev(d$correct_ci_high)),
      col = adjustcolor(policy_colours[[policy]], alpha.f = 0.12),
      border = NA
    )
    lines(d$ticks, d$correct_choice_rate, col = policy_colours[[policy]], lwd = 2.6)
  }
  text(25, 0.04, "Teacher evidence\nshared", pos = 4, cex = 0.72, col = "#53616D")
  title(if (world == "B-good") "World: B is better" else "World: B is worse", col.main = dark)
}
par(fig = c(0, 1, 0, 1), mar = c(0, 0, 0, 0), new = TRUE)
plot.new()
legend(
  "bottom",
  inset = c(0, 0.018),
  legend = c("No deference", "Preemption", "Total evidence"),
  col = unname(policy_colours),
  lwd = 3,
  horiz = TRUE,
  bty = "n",
  cex = 0.9
)
mtext("Experiment 1: learning paths", side = 3, outer = TRUE, line = 0.7, font = 2, cex = 1.35, col = dark)
dev.off()

# Figure 3: recovery when the teacher's evidence packet points the wrong way.
recovery <- read.csv("recovery_summary.csv", check.names = FALSE)
recovery <- recovery[recovery$expert_status == "Incorrect", ]
recovery$policy <- factor(
  recovery$policy,
  levels = c("No Deference", "E-Preemption", "E-Total Evidence")
)
recovery <- recovery[order(recovery$world, recovery$policy), ]

open_png("figure_3_recovery_from_misleading_evidence.png", 1650, 1050)
par(mar = c(7.8, 6.0, 5.5, 2.0), oma = c(2.0, 0, 2.8, 0))
worlds <- c("B-good", "B-bad")
policies <- levels(recovery$policy)
mat <- sapply(worlds, function(w) {
  d <- recovery[recovery$world == w, ]
  d$median_recovery_delay_uncensored[match(policies, d$policy)]
})
colnames(mat) <- c("B is better", "B is worse")
bp <- barplot(
  mat,
  beside = TRUE,
  col = unname(policy_colours[policies]),
  border = NA,
  ylim = c(0, max(mat) * 1.25),
  ylab = "Median ticks to recovery",
  names.arg = colnames(mat),
  col.axis = dark,
  col.lab = dark,
  cex.names = 0.95,
  bty = "n"
)
abline(h = pretty(c(0, max(mat))), col = grid, lwd = 1)
axis(2, col.axis = dark)
for (j in seq_len(ncol(mat))) {
  text(bp[, j], mat[, j] + 1.1, labels = mat[, j], cex = 0.9, col = dark)
}
legend(
  "topright",
  legend = c("No deference", "Preemption", "Total evidence"),
  fill = unname(policy_colours),
  border = NA,
  bty = "n",
  cex = 0.9
)
mtext("Experiment 1: recovery after misleading teacher evidence", side = 3, outer = TRUE, line = 0.4, font = 2, cex = 1.35, col = dark)
mtext("Recovery: first 20-round window averaging >=60% correct choices; medians among recovered runs.", side = 1, outer = TRUE, line = 0.2, cex = 0.82, col = "#53616D")
dev.off()

cat("Static figures written to:", normalizePath(out_dir), "\n")

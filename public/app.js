const revealItems = document.querySelectorAll("[data-reveal]");

const revealObserver = new IntersectionObserver(
  (entries, observer) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        const delay = Number(entry.target.dataset.delay || 0);
        setTimeout(() => {
          entry.target.classList.add("revealed");
        }, delay);
        observer.unobserve(entry.target);
      }
    });
  },
  { threshold: 0.2 }
);

revealItems.forEach((item) => revealObserver.observe(item));

const statValues = document.querySelectorAll(".stat-value");
let countersStarted = false;
let statsReady = false;
let startPending = false;

const runCounters = () => {
  if (countersStarted) return;
  if (!statsReady) {
    startPending = true;
    return;
  }
  countersStarted = true;
  statValues.forEach((stat) => {
    const target = Number(stat.dataset.target || 0);
    let current = 0;
    const step = Math.max(1, Math.floor(target / 40));

    const tick = () => {
      current = Math.min(current + step, target);
      stat.textContent = current.toString();
      if (current < target) {
        requestAnimationFrame(tick);
      }
    };

    tick();
  });
};

const statsSection = document.querySelector(".stat-grid");
if (statsSection) {
  const statsObserver = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          runCounters();
        }
      });
    },
    { threshold: 0.4 }
  );

  statsObserver.observe(statsSection);
}

const applyStats = (stats) => {
  const values = [
    stats.total_accounts ?? 0,
    stats.active_rentals ?? 0,
    stats.available_accounts ?? 0,
  ];

  statValues.forEach((stat, index) => {
    const value = Number(values[index] ?? 0);
    stat.dataset.target = value.toString();
    if (!countersStarted) {
      stat.textContent = "0";
    }
  });
};

const loadStats = async () => {
  try {
    const response = await fetch("/api/stats");
    if (!response.ok) {
      statsReady = true;
      return;
    }
    const payload = await response.json();
    applyStats(payload);
  } catch (error) {
    console.warn("Failed to load stats.", error);
  } finally {
    statsReady = true;
    if (startPending) {
      runCounters();
    }
  }
};

loadStats();

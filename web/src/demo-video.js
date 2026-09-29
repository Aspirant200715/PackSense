const dialog = document.querySelector("#product-film-dialog");
const film = document.querySelector("#product-film");
const stopFilm = () => {
  film.pause();
  if (film.readyState > 0) film.currentTime = 0;
};
const closeFilm = () => {
  stopFilm();
  dialog.close();
};

document.querySelectorAll("[data-watch-demo]").forEach((button) => {
  button.addEventListener("click", () => {
    dialog.showModal();
    film.play().catch(() => { /* Controls remain available if autoplay is blocked. */ });
  });
});

document.querySelector("#product-film-close").addEventListener("click", closeFilm);
dialog.addEventListener("click", (event) => { if (event.target === dialog) closeFilm(); });
dialog.addEventListener("cancel", stopFilm);
dialog.addEventListener("close", stopFilm);


document.addEventListener("DOMContentLoaded", function(){
  const ids = ['#ordersTable', '#deliveriesTable', '#clientsTable'];
  ids.forEach(sel => {
    const el = document.querySelector(sel);
    if(!el) return;
    new DataTable(el, {
      paging: true,
      searching: true,
      info: true,
      ordering: true,
      pageLength: 10,
      language: {
        url: 'https://cdn.datatables.net/plug-ins/2.1.8/i18n/fr-FR.json'
      }
    });
  });
});

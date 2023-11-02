
  function initSelectOptions(selectID) {
    for (const k in availableItems){
      console.log(k);
      $(selectID).append($('<option>', {
        value: k,
        text: availableItems[k].display_name
      }));
    }
  }

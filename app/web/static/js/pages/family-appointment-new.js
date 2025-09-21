// Family Appointment New Form JavaScript
document.addEventListener('DOMContentLoaded', function() {
  const dateInput = document.getElementById('date');
  const professionalSelect = document.getElementById('professional_id');
  const timeSelect = document.getElementById('time');
  const loadSlotsBtn = document.getElementById('load-slots-btn');
  const slotsStatus = document.getElementById('slots-status');
  const serviceInput = document.getElementById('service');
  const locationSelect = document.getElementById('location');
  
  // Simple test to see if the script is loading
  console.log('Family appointment new script loaded');
  
  // Store professional data for service and location lookup
  const professionalData = {};
  
  // Populate professional data from the select options
  if (professionalSelect) {
    Array.from(professionalSelect.options).forEach(option => {
      if (option.value) {
        // Extract service from the option text (format: "Name (Service)")
        const text = option.textContent;
        const match = text.match(/\((.+)\)$/);
        if (match) {
          professionalData[option.value] = {
            service: match[1],
            location: 'Sala 101' // Default location, can be customized
          };
        } else {
          professionalData[option.value] = {
            service: text,
            location: 'Sala 101'
          };
        }
      }
    });
    
    // Handle professional selection
    professionalSelect.addEventListener('change', function(e) {
      const professionalId = e.target.value;
      
      // Reset time select when professional changes
      if (timeSelect) {
        timeSelect.innerHTML = '<option value="">Informe a data e clique em "Buscar horários"</option>';
        timeSelect.disabled = true;
      }
      
      // Reset slots status
      if (slotsStatus) {
        slotsStatus.textContent = '';
      }
      
      // Set service based on professional
      if (serviceInput && professionalData[professionalId]) {
        serviceInput.value = professionalData[professionalId].service;
      }
      
      // Set location based on professional
      if (locationSelect && professionalData[professionalId]) {
        // Clear and repopulate location options
        locationSelect.innerHTML = '';
        const option = document.createElement('option');
        option.value = professionalData[professionalId].location;
        option.textContent = professionalData[professionalId].location;
        locationSelect.appendChild(option);
        locationSelect.value = professionalData[professionalId].location;
      } else if (locationSelect) {
        locationSelect.innerHTML = '<option value="">Selecione um profissional primeiro</option>';
        locationSelect.value = '';
      }
    });
  }
  
  // Format date as user types (simplified)
  if (dateInput) {
    console.log('Date input found');
    dateInput.addEventListener('input', function(e) {
      console.log('Date input event:', e.target.value);
      let value = e.target.value;
      
      // Only format when user types digits
      if (/^\d+$/.test(value.replace(/\//g, ''))) {
        // Add slashes as user types (but don't be too aggressive)
        if (value.length === 2 && !value.includes('/')) {
          value = value + '/';
        } else if (value.length === 5 && (value.match(/\//g) || []).length === 1) {
          value = value + '/';
        }
        
        // Limit to 10 characters
        if (value.length > 10) {
          value = value.substring(0, 10);
        }
        
        e.target.value = value;
      }
      
      console.log('Formatted value:', e.target.value);
    });
    
    // Validate date format on blur
    dateInput.addEventListener('blur', function(e) {
      const value = e.target.value;
      console.log('Date blur event:', value);
      if (value) {
        const isValid = validateDateFormat(value);
        console.log('Date is valid:', isValid);
        if (!isValid) {
          e.target.setCustomValidity('Formato de data inválido. Use DD/MM/AAAA.');
        } else {
          e.target.setCustomValidity('');
        }
      }
    });
  } else {
    console.log('Date input not found');
  }
  
  // Validate date format (DD/MM/YYYY)
  function validateDateFormat(dateStr) {
    const datePattern = /^\d{2}\/\d{2}\/\d{4}$/;
    if (!datePattern.test(dateStr)) {
      return false;
    }
    
    const [day, month, year] = dateStr.split('/').map(Number);
    const date = new Date(year, month - 1, day);
    
    return date.getDate() === day && 
           date.getMonth() === month - 1 && 
           date.getFullYear() === year;
  }
  
  // Function to load available slots
  async function loadAvailableSlots() {
    const professionalId = professionalSelect ? professionalSelect.value : '';
    const dateValue = dateInput ? dateInput.value : '';
    
    console.log('Loading slots for professional:', professionalId, 'date:', dateValue);
    
    // Reset status and time select
    if (slotsStatus) {
      slotsStatus.textContent = '';
    }
    
    // Validate inputs
    if (!professionalId) {
      if (slotsStatus) {
        slotsStatus.textContent = 'Selecione um profissional primeiro.';
        slotsStatus.style.color = 'var(--danger)';
      }
      if (timeSelect) {
        timeSelect.innerHTML = '<option value="">Selecione um profissional</option>';
        timeSelect.disabled = true;
      }
      return;
    }
    
    if (!dateValue) {
      if (slotsStatus) {
        slotsStatus.textContent = 'Informe a data primeiro.';
        slotsStatus.style.color = 'var(--danger)';
      }
      if (timeSelect) {
        timeSelect.innerHTML = '<option value="">Informe a data</option>';
        timeSelect.disabled = true;
      }
      return;
    }
    
    // Validate date format
    if (!validateDateFormat(dateValue)) {
      if (slotsStatus) {
        slotsStatus.textContent = 'Formato de data inválido. Use DD/MM/AAAA.';
        slotsStatus.style.color = 'var(--danger)';
      }
      if (timeSelect) {
        timeSelect.innerHTML = '<option value="">Data inválida</option>';
        timeSelect.disabled = true;
      }
      return;
    }
    
    // Show loading status
    if (slotsStatus) {
      slotsStatus.textContent = 'Buscando horários disponíveis...';
      slotsStatus.style.color = 'var(--muted)';
    }
    if (timeSelect) {
      timeSelect.innerHTML = '<option value="">Carregando...</option>';
      timeSelect.disabled = true;
    }
    
    // Convert DD/MM/YYYY to YYYY-MM-DD for API
    const [day, month, year] = dateValue.split('/');
    const apiDate = `${year}-${month.padStart(2, '0')}-${day.padStart(2, '0')}`;
    
    try {
      // Make sure we're sending the right parameters
      const url = `/family/appointments/slots?professional_id=${professionalId}&date=${dateValue}`;
      console.log('Fetching slots from URL:', url);
      
      const response = await fetch(url);
      console.log('Slots API response status:', response.status);
      
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      
      const data = await response.json();
      console.log('Slots API response data:', data);
      
      if (timeSelect) {
        if (data.slots && data.slots.length > 0) {
          timeSelect.innerHTML = '<option value="">Selecione um horário</option>';
          data.slots.forEach(slot => {
            const option = document.createElement('option');
            option.value = slot;
            option.textContent = slot;
            timeSelect.appendChild(option);
          });
          timeSelect.disabled = false;
          
          if (slotsStatus) {
            slotsStatus.textContent = `Encontrados ${data.slots.length} horários disponíveis.`;
            slotsStatus.style.color = 'var(--success)';
          }
        } else {
          timeSelect.innerHTML = '<option value="">Nenhum horário disponível</option>';
          timeSelect.disabled = true;
          
          if (slotsStatus) {
            slotsStatus.textContent = 'Nenhum horário disponível para esta data.';
            slotsStatus.style.color = 'var(--danger)';
          }
        }
      }
    } catch (error) {
      console.error('Error loading slots:', error);
      if (timeSelect) {
        timeSelect.innerHTML = '<option value="">Erro ao carregar horários</option>';
        timeSelect.disabled = true;
      }
      if (slotsStatus) {
        slotsStatus.textContent = 'Erro ao buscar horários. Tente novamente.';
        slotsStatus.style.color = 'var(--danger)';
      }
    }
  }
  
  // Event listeners
  if (loadSlotsBtn) {
    loadSlotsBtn.addEventListener('click', loadAvailableSlots);
  }
  
  // Also load slots when professional changes
  if (professionalSelect) {
    professionalSelect.addEventListener('change', function() {
      // Reset time select when professional changes
      if (timeSelect) {
        timeSelect.innerHTML = '<option value="">Informe a data e clique em "Buscar horários"</option>';
        timeSelect.disabled = true;
      }
      if (slotsStatus) {
        slotsStatus.textContent = '';
      }
    });
  }
});
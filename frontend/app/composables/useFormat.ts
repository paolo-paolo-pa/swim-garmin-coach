// Formatting adapter for reused Coach Watts presentation components.
export function useFormat(){
 const formatDateUTC=(value:string|Date,pattern?:string)=>{
  const options:Intl.DateTimeFormatOptions=pattern==='EEE'?{weekday:'short'}:pattern==='EEEE'?{weekday:'long'}:pattern==='d'?{day:'numeric'}:pattern==='MMM d'?{day:'numeric',month:'short'}:{weekday:'short',day:'numeric',month:'short'}
  return new Intl.DateTimeFormat('it-IT',{...options,timeZone:'UTC'}).format(new Date(value))
 }
 const formatTime=(value:string)=>new Intl.DateTimeFormat('it-IT',{hour:'2-digit',minute:'2-digit'}).format(new Date(value))
 return {formatDateUTC,formatTime}
}
